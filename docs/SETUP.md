# Email Setup Guide

LinkedInScript sends you a daily email digest of new internship listings. This guide walks you through configuring Gmail SMTP to enable email delivery.

## Prerequisites

- Python 3.12+ installed
- Gmail account (personal or Google Workspace)
- 2-Step Verification enabled on your Google account

## Step 1: Enable 2-Step Verification

If you haven't already enabled 2FA on your Google account:

1. Go to https://myaccount.google.com/security
2. Under "How you sign in to Google", click **2-Step Verification**
3. Follow the prompts to enable it (phone number or authenticator app)

You **must** have 2-Step Verification enabled before you can generate an App Password.

## Step 2: Generate App Password

1. Go directly to https://myaccount.google.com/apppasswords
2. You may need to re-enter your Google password
3. Under "App name", type `LinkedInScript` (or any name you'll recognize)
4. Click **Create**
5. Google displays a 16-character password (shown in groups of 4, like `abcd efgh ijkl mnop`)
6. Copy this password immediately — you cannot view it again after closing the dialog

**Note:** The spaces between groups are display-only. You can enter the password with or without spaces — both work. The actual password is 16 characters.

## Step 3: Configure .env

Create a `.env` file in the project root (same directory as `main.py`):

```
EMAIL_PASSWORD=abcdefghijklmnop
```

**Important:**
- No quotes around the password value
- No spaces in the password (remove the display spaces if you copied them with spaces)
- The `.env` file is already in `.gitignore` — it will never be committed to version control

## Step 4: Configure config.yaml

Open `config.yaml` and update the email section:

```yaml
email:
  enabled: true
  smtp_host: "smtp.gmail.com"
  smtp_port: 587
  sender_email: "your.email@gmail.com"
  recipient_email: "your.email@gmail.com"
```

- `enabled: true` — activates email sending
- `sender_email` — the Gmail address that generated the App Password
- `recipient_email` — where to receive the digest (can be the same address)

## Step 5: Verify Setup

Run the test command:

```
python main.py --test-email
```

Expected output on success:

```
[1/4] Checking email configuration...
[1/4] Configuration OK.
[2/4] Connecting to smtp.gmail.com:587...
[2/4] Connected with STARTTLS.
[3/4] Authenticating...
[3/4] Authentication successful.
[4/4] Sending test message to your.email@gmail.com...
[4/4] Test email sent successfully! Check your inbox.
```

Exit code 0 means success. Exit code 1 means something failed — check the error message.

## Windows Task Scheduler Notes

When running LinkedInScript via Task Scheduler, be aware of the following:

### Working Directory

Set the **"Start in (optional)"** field in the Task Scheduler action to your project directory:

```
C:\Users\YourName\projects\LinkedInScript
```

While the code resolves paths absolutely via `Path(__file__).resolve().parent`, setting the working directory is a best practice that avoids edge cases.

### .env File Loading

The `.env` file is loaded using an absolute path (`PROJECT_ROOT / ".env"`), so it works correctly regardless of the working directory. Task Scheduler's session context does not affect this.

### Environment Variables

Environment variables set in the Task Scheduler "Edit action" dialog are **NOT** the same as your `.env` file. Always use the `.env` file approach for `EMAIL_PASSWORD` — do not rely on Windows system environment variables or Task Scheduler action-level variables.

### Virtual Environment

If using a virtual environment, set the **Program/script** field to the full path of the Python executable inside your venv:

```
C:\Users\YourName\projects\LinkedInScript\.venv\Scripts\python.exe
```

And set **Add arguments** to:

```
main.py
```

### Run Whether User Is Logged On

Enable "Run whether user is logged on or not" in the task's General tab. This ensures the script runs even when you're not at the computer.

## Troubleshooting

### SMTPAuthenticationError (535)

**Cause:** Wrong password, 2FA not enabled, or App Password created for a different Google account.

**Fix:**
1. Verify 2-Step Verification is enabled at https://myaccount.google.com/security
2. Generate a new App Password at https://myaccount.google.com/apppasswords
3. Ensure the password in `.env` matches exactly (no extra spaces or quotes)
4. Confirm `sender_email` in `config.yaml` matches the Google account that owns the App Password

### Connection Timeout

**Cause:** Firewall blocking port 587, or network not ready (Task Scheduler firing at boot before network is up).

**Fix:**
1. Ensure your firewall allows outbound connections on port 587
2. In Task Scheduler, set a delay: under Triggers, check "Delay task for" and set to 1-2 minutes
3. Enable "Start the task only if the following network connection is available" under Conditions

### Email Goes to Spam

**Cause:** Unusual for self-to-self emails, but can happen with mismatched headers.

**Fix:**
1. Ensure `sender_email` and `recipient_email` match (self-to-self avoids SPF issues)
2. Check your Gmail Spam folder and mark the message "Not spam"
3. Gmail learns quickly — after 1-2 manual "Not spam" actions it stops flagging

### "Less Secure App Access" Confusion

This setting was **removed by Google in May 2022**. It no longer exists. If you find old tutorials mentioning it, ignore them. The only way to use SMTP with a personal Gmail account in 2024+ is via App Passwords (which require 2-Step Verification).

### Google Workspace / School Accounts

Some organizations disable App Passwords entirely. If you see "The setting you are looking for is not available for your account", contact your Google Workspace administrator. Alternatively, use a personal Gmail account as the sender.

### Copied Password with Extra Spaces

Google displays App Passwords in groups of four (`abcd efgh ijkl mnop`). The actual password is 16 characters with no spaces. If you copied it with spaces, either:
- Remove all spaces: `abcdefghijklmnop`
- Or leave spaces in — Gmail SMTP accepts both formats

Either way, the password in your `.env` should be exactly as shown (with or without spaces, both work).

## Security Notes

- **Never commit `.env`** — it's already in `.gitignore` for this project
- **App Passwords can be revoked** anytime at https://myaccount.google.com/apppasswords
- **Use a dedicated sender account** if concerned about security — create a separate Gmail just for this tool
- **App Passwords bypass 2FA** for the specific app — if your `.env` is compromised, revoke the App Password immediately
- **The password is never logged** — LinkedInScript only uses it for the SMTP connection, never prints or stores it

---

## Task Scheduler Setup

Automate LinkedInScript to run daily without manual effort using Windows Task Scheduler.

### Prerequisites

- Windows 11 (or Windows 10 with PowerShell 5.1+)
- Python 3.12+ installed (in a virtual environment or system-wide)
- Project fully configured (`config.yaml` exists, email working via `--test-email`)
- PowerShell execution policy set to **RemoteSigned** or **Unrestricted**

### Execution Policy

If you see "running scripts is disabled on this system" when running the install script, your execution policy is set to `Restricted`. Fix it by running this command in PowerShell (no admin required):

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

The install script checks for this and warns you, but cannot fix it automatically.

### Installation

1. Open **PowerShell as Administrator** (right-click PowerShell, "Run as administrator")

2. Navigate to the project directory:
   ```powershell
   cd C:\path\to\LinkedInScript
   ```

3. Run the install script:
   ```powershell
   .\scripts\install-task.ps1
   ```

   Or with an explicit Python path (if auto-detection fails):
   ```powershell
   .\scripts\install-task.ps1 -PythonPath "C:\Users\YourName\.venv\Scripts\python.exe"
   ```

4. The script will confirm successful registration with a summary of settings.

**Note:** The script is idempotent — safe to re-run anytime to update settings (uses `-Force` internally). No need to uninstall first when changing configuration.

### What It Does

Creates a scheduled task named **"LinkedInScript"** in Windows Task Scheduler that:
- Runs daily at the time specified in `config.yaml` under `schedule.time` (default: 08:00)
- Uses `StartWhenAvailable` — if your PC was off at the scheduled time, runs at next opportunity
- Sets the working directory to the project root (so relative paths work correctly)
- Limits execution time to 1 hour (prevents runaway processes)
- Requires network connectivity before starting

### Configuration

The schedule time is controlled by `config.yaml`:

```yaml
schedule:
  time: "08:00"  # Daily run time (24h format HH:MM)
```

Change the time and re-run `.\scripts\install-task.ps1` to update the schedule (no uninstall needed).

### Key Behaviors

- **StartWhenAvailable:** If your PC was off at 08:00, the task runs at the next opportunity when you log in. No missed days as long as you turn on your PC at some point.
- **Run only when logged on:** The default registration does not store your password. The task runs when you are logged in. For running while logged out, you would need to re-register with stored credentials (advanced — see Windows Task Scheduler documentation).
- **Manual trigger:** Run `python main.py` from the command line anytime for an on-demand check.
- **Check status:** Run `python main.py --status` to see last run time, consecutive failures, and next scheduled time.

### Verification

Confirm the task is registered correctly:

**PowerShell:**
```powershell
Get-ScheduledTask -TaskName 'LinkedInScript'
```

**Task Scheduler GUI:**
Open Task Scheduler (search "Task Scheduler" in Start), look for "LinkedInScript" in the root folder.

**CLI status check:**
```
python main.py --status
```

This shows last run time, failure count, and next scheduled time.

### Uninstall

Remove the scheduled task cleanly:

```powershell
# Run from admin PowerShell in the project directory
.\scripts\uninstall-task.ps1
```

Safe to run even if the task is not currently registered (exits gracefully).

### Troubleshooting

**"Running scripts is disabled on this system"**

Your execution policy is set to `Restricted`. Run this in PowerShell (no admin needed):
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```
Then retry the install script.

**"Python not found" during install**

The script could not auto-detect your Python installation. Use the `-PythonPath` parameter with the full path to `python.exe` in your virtual environment:
```powershell
.\scripts\install-task.ps1 -PythonPath "C:\Users\YourName\projects\LinkedInScript\.venv\Scripts\python.exe"
```

**Task shows "Queued" but never runs**

`StartWhenAvailable` requires the user to be logged in (since no password is stored). Verify with:
```powershell
Get-ScheduledTask -TaskName 'LinkedInScript' | Select-Object State
```
If state is "Queued", log in and wait a moment — it should trigger automatically.

**Task registered but script fails silently**

1. Check logs at `logs/run.log` for error details
2. Run `python main.py` manually from the project directory to see the full output
3. Verify your virtual environment is activated and dependencies are installed
4. Run `python main.py --status` to check the run history

**Want to change the schedule time**

Edit `config.yaml` and update `schedule.time` to your desired time (24h format, e.g., `"14:30"`), then re-run `.\scripts\install-task.ps1`. The `-Force` flag handles re-registration automatically — no need to uninstall first.

**"Access denied" or "requires elevation"**

The install script requires Administrator privileges. Right-click PowerShell and select "Run as administrator" before running the script.
