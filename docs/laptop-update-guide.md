# Moving the firm's laptop to the new version

These are the exact steps for moving the firm's laptop from the old installed copy to a fresh copy of the latest version, by installing Git and cloning the repository. Your data, settings and backups are kept. The old folder stays as a fallback until you delete it.

Everything below runs in an **Administrator PowerShell** on the laptop (right-click PowerShell, then Run as administrator), signed in as the same Windows user who installed the app. The examples assume the app is at `C:\TaskBoard`. If yours is somewhere else, use your own path everywhere.

Plan for about 30 minutes at a quiet time. The app is unavailable while you work.

## What you will end up with

- The latest version running from `C:\TaskBoard`, as a Git checkout, so future updates are one command.
- All tasks, updates, people, passwords, settings and backups unchanged.
- On the first start, everyone on an open task gets one unread notification for it in their bell, so existing work shows up right away. These are bell-only: no pop-up and no desktop alert.
- The old copy in `C:\TaskBoard-old`, untouched, until you delete it.

## Part 1: Moving to the new version

### Step 1. Check where your data lives

Open `C:\TaskBoard\.env` in Notepad and look at `DATA_DIR` and `BACKUP_DIR`.

- If they are relative (the default `data` and `backups`), the folders sit inside `C:\TaskBoard`, and step 5 copies them.
- If either is an absolute path somewhere else (for example a OneDrive folder), that data does not move and needs no copying. Only the `.env` file is copied.

### Step 2. Install Git

```powershell
winget install --id Git.Git -e
```

If `winget` is not available, download and run the installer from https://git-scm.com/download/win and accept all the default options.

Then **close PowerShell and open a new Administrator PowerShell**, and check:

```powershell
git --version
```

It should print a version number.

### Step 3. Stop the app and put the old folder aside

```powershell
cd C:\
powershell -ExecutionPolicy Bypass -File C:\TaskBoard\deploy\windows\restart.ps1 -Stop
Rename-Item C:\TaskBoard TaskBoard-old
```

The `cd C:\` matters: the rename fails if PowerShell is sitting inside the folder. If the rename says the folder is in use, close any Explorer or Notepad windows that have it open and try again.

### Step 4. Clone the latest version into the same path

```powershell
git clone https://github.com/TathagatAgrawal/simple-task-management.git C:\TaskBoard
```

- If the repository is private, a GitHub sign-in window opens. Sign in once; it is remembered for this Windows user. Use the same Windows user that installed the app, because the app's update check and the nightly update reuse that saved sign-in.
- If you see a "dubious ownership" error, run `git config --global --add safe.directory C:/TaskBoard` and run the clone check again with `git -C C:\TaskBoard status`.

### Step 5. Copy your settings and data into the new folder

```powershell
Copy-Item C:\TaskBoard-old\.env C:\TaskBoard\.env
Copy-Item C:\TaskBoard-old\data C:\TaskBoard\data -Recurse
Copy-Item C:\TaskBoard-old\backups C:\TaskBoard\backups -Recurse
Copy-Item C:\TaskBoard-old\logs C:\TaskBoard\logs -Recurse
```

Skip any line for a folder that does not exist. **Do not copy `.venv`**: the installer rebuilds it. Then check that the database arrived:

```powershell
Get-Item C:\TaskBoard\data\tasks.db
```

### Step 6. Run the installer from the new folder

```powershell
cd C:\TaskBoard
powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1
```

Answer the prompts like this:

- **Create an admin account now?** Type `n`. Your admins are already in the copied data.
- **The Windows password window:** enter this PC's Windows password. This replaces the old scheduled task so it points at the new folder.
- **Set this PC to never sleep?** Type `n` if you already set that up before.

The installer installs the dependencies, registers the task, starts the app and runs `tailscale serve` again (safe to repeat). On the first start the database upgrades itself.

### Step 7. Check that it works and that nothing was lost

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\status.ps1
```

You want the scheduled task running, the health check `OK`, and Tailscale serving.

Then compare the data counts. The two lines of three numbers (tasks, updates, people) should be identical:

```powershell
cd C:\TaskBoard-old
uv run --no-dev python -c "import sqlite3; c=sqlite3.connect('data/tasks.db'); print([c.execute('select count(*) from '+t).fetchone()[0] for t in ('tasks','updates','users')])"
cd C:\TaskBoard
uv run --no-dev python -c "import sqlite3; c=sqlite3.connect('data/tasks.db'); print([c.execute('select count(*) from '+t).fetchone()[0] for t in ('tasks','updates','users')])"
```

Then, from another device over the Tailscale address, sign in and check:

1. The board shows the same tasks as before.
2. The bell shows unread notifications for each person's existing tasks, and nothing pops up.
3. Open the app in two windows signed in as two people, move a card in one, and the other updates by itself within a second or two.

### Step 8. Tell everyone to refresh

Everyone refreshes the page once with Ctrl+F5. Close and reopen the app on any phone where it was added to the home screen.

### Step 9. Clean up later

Keep `C:\TaskBoard-old` for about a week. When you are happy, delete it.

## Part 2 (optional): Automatic updates

The app can look for new versions, and the laptop can install them by itself at night. Nothing installs by itself unless **both** of these are on: the nightly task on the PC (step A), and the switch in the app (step B).

### A. Turn on nightly updates

Run once in an Administrator PowerShell:

```powershell
cd C:\TaskBoard
powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1 -EnableAutoUpdate
```

It asks for this PC's Windows password (so the task can run when nobody is signed in) and sets up a daily task at 03:00.

### B. Turn on the switch in the app

An admin opens the user menu, then **Updates**, and turns on **Update automatically at night**.

From then on, each night the laptop looks for a new version. If there is one, it takes a backup, installs it, restarts the app (unavailable for a minute or two), checks that all the tasks and people are still there, and puts the old version back if the new one will not start. The **Updates** window shows what the last automatic run did.

### Choose the time

The time is a 24-hour time on the PC's own clock. Run the command again with the time you want. It replaces the existing task and asks for the Windows password again:

```powershell
cd C:\TaskBoard
powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1 -EnableAutoUpdate -At 02:30
```

Pick a time when nobody is working and that is not close to the nightly backup (23:00 by default). Alternatively, open **Task Scheduler** (press the Windows key, type `Task Scheduler`), select **Task Scheduler Library**, double-click **TaskBoardUpdate**, open the **Triggers** tab, and edit the trigger.

### Turn automatic updates off

There are three levels. Use the first for a quick pause and the last to stop everything.

1. **Pause installing, keep looking.** An admin turns off **Update automatically at night** in the app (user menu, **Updates**). The nightly task keeps running, but it only looks and records "a new version is waiting"; it installs nothing. You can turn it back on at any time.
2. **Remove the nightly task.** Run in an Administrator PowerShell:

   ```powershell
   cd C:\TaskBoard
   powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1 -DisableAutoUpdate
   ```

   The app still shows when a new version is available, and you update by hand with `update.ps1`.
3. **Stop the app looking for updates at all.** Edit `C:\TaskBoard\.env`, add the line `UPDATE_CHECK=0`, then restart the app:

   ```powershell
   cd C:\TaskBoard
   powershell -ExecutionPolicy Bypass -File deploy\windows\restart.ps1
   ```

### Check that it is set up, and try it once

```powershell
cd C:\TaskBoard
powershell -ExecutionPolicy Bypass -File deploy\windows\status.ps1
```

It shows whether the nightly task exists and when it runs next. To try it now instead of waiting for the night, run the task once and read the result:

```powershell
Start-ScheduledTask -TaskName TaskBoardUpdate
Get-Content C:\TaskBoard\logs\update.log -Tail 30
```

If **Update automatically at night** is off, the log should say that automatic updates are turned off and nothing was installed. If it is on and a new version is waiting, it installs. The **Updates** window shows the result as well.

## Part 3: Later updates by hand

The folder is now a Git checkout, so any time you want to update:

```powershell
cd C:\TaskBoard
powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1 -CheckOnly
powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1
```

The first command only shows what is new. The second prints the data counts, takes a backup, installs, checks, and prints the counts again. It puts the old version back by itself if the new one will not start.

## If something goes wrong during Part 1

Stop the app, then swap the folders back:

```powershell
powershell -ExecutionPolicy Bypass -File C:\TaskBoard\deploy\windows\restart.ps1 -Stop
cd C:\
Rename-Item C:\TaskBoard TaskBoard-new
Rename-Item C:\TaskBoard-old TaskBoard
powershell -ExecutionPolicy Bypass -File C:\TaskBoard\deploy\windows\install.ps1
```

The old `data` folder was never changed, so the old version comes back exactly as it was. If people already added work in the new version, first copy `C:\TaskBoard-new\data\tasks.db` over `C:\TaskBoard-old\data\tasks.db` before the rename. The old version runs fine on the upgraded database, so no work is lost.

If a step fails or prints a red error, stop there and send the last lines of `C:\TaskBoard\logs\app.log` (and `logs\update.log` for update problems) to whoever looks after the app.

## Not yet tested

These scripts were written on a Mac with no PowerShell, so the first real run is on your laptop. Read each output line before moving on, and do Part 1 at a quiet time.
