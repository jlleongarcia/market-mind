# Off-site backup copy (Tailscale)

The homelab produces a daily encrypted DB backup (see `scripts/backup_db.sh`,
cron at 8:00 AM — details in `DEPLOYMENT.md`/project memory), but that backup
lives on the same physical machine as the live database. This guide sets up a
**second copy on another machine on the same Tailscale network** (e.g. a
laptop), so losing the homelab machine doesn't mean losing both the DB and its
only backup.

Design: the laptop **pulls** the backup from the homelab (not the other way
around) via SFTP, triggered on login/boot on the laptop — a push from the
homelab on a fixed cron time is unreliable since the laptop isn't always
on/connected at that moment.

---

## Why a dedicated, restricted account

The sync runs unattended, so it must not use a general-purpose, full-access
SSH identity (e.g. your normal Tailscale SSH login) — if the laptop is ever
compromised, that key would hand over full shell access to the homelab. This
setup instead uses:

- A **dedicated system user** (`backupsync`) with no sudo, no group
  memberships, `nologin` shell.
- A **chroot jail** containing *only* a read-only bind-mount of the backups
  folder — the account cannot see or touch anything else on the filesystem.
- A **separate SSH keypair**, generated on the laptop (private key never
  leaves it), restricted in `authorized_keys` to only be usable **from the
  laptop's Tailscale IP** (`from="..."`) and only for SFTP (`ForceCommand
  internal-sftp`, no shell/TTY/forwarding).

This is why it doesn't reuse **Tailscale SSH** (the mechanism normally used to
log into the homelab with full access): Tailscale SSH terminates connections
inside `tailscaled` itself, bypassing the system's sshd entirely — so sshd-level
restrictions like `ForceCommand`/`ChrootDirectory` can't be applied to it. A
conventional keypair authenticated by the homelab's own sshd (still only
reachable over the private Tailscale network) is what makes the jail possible.

---

## 1. Homelab: recover sudo access (only if missing)

Some homelab installs (Debian, or a minimized
Ubuntu image) don't provision `sudo` for the admin user out of the box —
`sudo <anything>` then fails with `sudo: command not found`.

**Do not** turn your admin user into `root` (no shared UID 0, no merging
accounts). Keep `root` as a separate, rarely-used emergency account, and
grant your admin user `sudo` group membership instead — same
least-privilege principle as the dedicated `backupsync` account below.

If you don't know the root password, this requires **physical/console
access** to the machine (SSH alone can't grant root without a known
credential, by design):

1. Reboot, and at boot hold **Shift** (BIOS) or **Esc** (UEFI) to reach the
   GRUB menu.
2. Select **Advanced options for Ubuntu** → the **recovery mode** entry.
3. In the recovery menu, pick **network** first (enables networking —
   needed for `apt`).
4. Then pick **root** — *Drop to root shell prompt*.
5. The filesystem is mounted read-only in recovery mode, so first:
   ```bash
   mount -o remount,rw /
   ```
6. Install sudo and grant it to your admin user (replace `username`
   with your actual username):
   ```bash
   apt update && apt install -y sudo
   usermod -aG sudo username
   ```
7. While you're here, set a root password too, so a future fix doesn't
   require physical access again:
   ```bash
   passwd root
   ```
8. Exit back to the recovery menu and choose **resume** (or reboot).
9. Log out/in over SSH as your admin user (group membership needs a fresh
   session), then confirm with:
   ```bash
   sudo -v
   ```

Once `sudo -v` works, continue to Step 2.

---

## 2. Laptop: generate a dedicated keypair

On the laptop (native Windows OpenSSH — `ssh-keygen`/`sftp` are bundled with
Windows 10/11; no WSL or third-party client needed):

```powershell
ssh-keygen -t ed25519 -f $HOME\.ssh\market-mind-backupsync -C "market-mind-backup-sync"
```

Empty passphrase is reasonable here since the key can only read the backups
folder from this one machine's Tailscale IP — the blast radius of the key
file alone leaking is low. Use a passphrase + `ssh-agent` instead if you'd
rather not have an unencrypted private key on disk at all.

The private key **never leaves the laptop**. Copy the `.pub` file's contents
into the homelab setup script's `LAPTOP_PUBKEY` variable (step 3 below).

---

## 3. Homelab: jailed, read-only, sftp-only account

Requirements: Linux homelab with OpenSSH server (tested on Ubuntu 24.04 /
OpenSSH 9.6), root/sudo access, `mount --bind` support.

Run as root/sudo (idempotent — safe to re-run):

```bash
#!/bin/bash
set -euo pipefail

BACKUPS_SRC="<absolute path to your market-mind/backups directory>"
JAIL_ROOT="/srv/backup-mirror"
JAIL_MOUNT="$JAIL_ROOT/market-mind-backups"
LAPTOP_TS_IP="<laptop's Tailscale IP, e.g. 100.x.x.x — see `tailscale status`>"
LAPTOP_PUBKEY="<contents of market-mind-backupsync.pub from the laptop>"

# 1. Dedicated low-privilege user
useradd --system --shell /usr/sbin/nologin --home-dir /home/backupsync --create-home backupsync

# 2. Restricted authorized_keys: only from the laptop's Tailscale IP
install -d -m 700 -o backupsync -g backupsync /home/backupsync/.ssh
echo "restrict,from=\"$LAPTOP_TS_IP\" $LAPTOP_PUBKEY" > /home/backupsync/.ssh/authorized_keys
chmod 600 /home/backupsync/.ssh/authorized_keys
chown backupsync:backupsync /home/backupsync/.ssh/authorized_keys

# 3. Root-owned chroot jail (ChrootDirectory requires root ownership of the
#    jail root and every parent dir — a separate /srv dir avoids having to
#    touch ownership of your actual home directory tree)
mkdir -p "$JAIL_ROOT" "$JAIL_MOUNT"
chown root:root "$JAIL_ROOT"
chmod 755 "$JAIL_ROOT"

# 4. Bind-mount the real backups dir read-only into the jail, persisted via fstab
mount --bind "$BACKUPS_SRC" "$JAIL_MOUNT"
mount -o remount,ro,bind "$JAIL_MOUNT"
echo "$BACKUPS_SRC $JAIL_MOUNT none bind,ro 0 0" >> /etc/fstab

# 5. sshd drop-in: force sftp-only, no shell, no forwarding
cat > /etc/ssh/sshd_config.d/10-backupsync.conf <<'EOF'
Match User backupsync
    ChrootDirectory /srv/backup-mirror
    ForceCommand internal-sftp -d /market-mind-backups
    X11Forwarding no
    AllowTcpForwarding no
    AllowAgentForwarding no
    PermitTTY no
EOF

# 6. Validate before reloading — never reload sshd blind
sshd -t
systemctl reload ssh
```

**Verify** (from the homelab itself, or after setting up the laptop side):

```bash
sftp backupsync@<homelab-tailscale-ip-or-magicdns-name>
# Should land directly in the jailed dir and list backup files
sftp> ls
sftp> get db_backup_YYYYMMDD_HHMMSS.sql.gz
sftp> put anything          # should fail — read-only mount
sftp> cd /                  # should fail to escape — chrooted
```

---

## 4. Laptop: sync script

Save as `Sync-MarketMindBackup.ps1` (adjust `$RemoteHost` to the homelab's
Tailscale IP or MagicDNS name, e.g. `myhomelab.<tailnet>.ts.net`):

```powershell
$RemoteHost   = "backupsync@<homelab-tailscale-ip-or-magicdns-name>"
$KeyPath      = "$HOME\.ssh\market-mind-backupsync"
$DestDir      = "$env:USERPROFILE\Backups\market-mind"
$LogFile      = "$DestDir\sync.log"
$RetentionDays = 30

New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

$batch = "$env:TEMP\mm_sftp_batch.txt"
"mget *`nbye" | Set-Content -Path $batch -Encoding ascii

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
try {
    Push-Location $DestDir
    & sftp.exe -i $KeyPath -b $batch $RemoteHost 2>&1 | Out-File -Append $LogFile
    Pop-Location
    "[$timestamp] Sync completed" | Out-File -Append $LogFile
} catch {
    "[$timestamp] ERROR: $_" | Out-File -Append $LogFile
}

# Prune local copies older than retention window
Get-ChildItem $DestDir -Filter "db_backup_*.sql.gz" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$RetentionDays) } |
    Remove-Item -Force

Remove-Item $batch -ErrorAction SilentlyContinue
```

`sftp.exe` (not `scp.exe`) is used deliberately — it speaks the same SFTP
protocol as the server's `internal-sftp`, avoiding version-dependent
ambiguity between legacy-scp and SFTP-based `scp` across different OpenSSH
client builds.

---

## 5. Laptop: schedule it

Windows Task Scheduler, one task, two triggers:

- **Daily**, e.g. 09:00 (an hour after the homelab's 8 AM backup) — with
  **"Run task as soon as possible after a scheduled start is missed"
  enabled**. This is Task Scheduler's built-in way of handling "daily, or as
  soon as possible after" without any extra scripting: if the laptop is
  off/asleep at 9 AM, it fires the moment the laptop is next usable.
- **At log on** — an explicit extra trigger so a sync is also attempted every
  time you log in, independent of the daily schedule's state.

Task settings:
- Action: `powershell.exe -ExecutionPolicy Bypass -File "C:\path\to\Sync-MarketMindBackup.ps1"`
- Condition: "Start only if the following network connection is available" → Any
- Do **not** restrict to AC power (it's a laptop)
- "Run only when user is logged on" (SSH key auth needs no stored Windows
  password, so there's no need for "run whether logged on or not")

---

## Verification checklist

- [ ] `sshd -t` passes and `systemctl reload ssh` succeeds on the homelab
- [ ] `mount | grep market-mind-backups` shows the bind mount as `ro`
- [ ] Manual `sftp backupsync@<host>` from the laptop lists backup files,
      cannot write, cannot `cd` outside the jail
- [ ] Manual run of `Sync-MarketMindBackup.ps1` produces a `.sql.gz` file in
      `%USERPROFILE%\Backups\market-mind`
- [ ] Task Scheduler task shows a successful run in its history after the
      next scheduled trigger or login
