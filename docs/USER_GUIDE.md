# HOLO User Guide

HOLO (Hands-On Lab Orchestrator) helps teams plan, build, review, and release
hands-on labs through an eight-phase workflow.

This guide covers the day-to-day tasks for Members, Managers, and Admins.

## 1. Sign in and get started

### Sign in

1. Open the HOLO URL provided by your organization.
2. Enter your email address and password.
3. Select **Log in**.
4. If this is your first login, HOLO sends you to **Change password**. Set a
   new password before continuing.

Your session remains active until you select **Log out**. Use **Change
password** in the top navigation whenever you need to update your password.

### Accept an invitation

HOLO accounts are created from single-use invitation links.

1. Open the invitation link sent by an Admin or Manager.
2. Confirm that the displayed email address is yours.
3. Create a password of at least eight characters.
4. Submit the registration form.

Invitation links expire and can only be used once. Ask a staff member to issue
another invitation if the link has expired or already been used.

## 2. Understand the roles

| Role | Main responsibility |
| --- | --- |
| **Member** | Create and work on labs, update tasks and planning information, and submit approval phases. |
| **Manager** | Everything a Member can do, plus approve submitted phases and use staff administration. |
| **Admin** | Staff administration, backups, notifications, system log, API documentation, and the Time Warp tool. Admins do not approve phases. |

The **Manager** is the approval gate. An Admin can manage the system but cannot
approve a phase submission.

## 3. Navigate HOLO

The top navigation provides:

- **Dashboard** — portfolio overview and lab status.
- **Mallmanac** — visual lifecycle map for all active labs.
- **New Lab** — create a lab.
- **Metrics** — staff-only portfolio metrics.
- **Admin** — users, invitations, backups, and system operations.
- **Notifications** — staff-only email configuration and subscriptions.
- **System Log** — staff-only audit history.
- **Change password** and **Log out** — account actions.

## 4. Dashboard

The Dashboard shows one card for every active lab. Each card includes:

- The lab name, course ID, owner, and target release.
- A progress bar with one segment for each of the eight phases.
- The lab status and completion percentage.
- The current phase.
- Actual hours compared with estimated hours.

Use the **Owner** filter to show only labs assigned to a specific person or
unassigned labs. Select **clear** to return to the full portfolio.

Managers also see an **Awaiting your approval** queue. Select a lab from the
queue to review its submission, or approve it directly from the queue.

## 5. Create a lab

Any signed-in user can create a lab.

1. Select **New Lab**.
2. Enter a descriptive **Lab name**.
3. Optionally enter a **Course ID**, **Target release**, and short **Abstract**.
4. Select **Create lab**.

HOLO creates the complete eight-phase pipeline automatically and makes the new
lab owner the record owner. The **Concept** phase starts active.

## 6. Work on a lab

Select a lab from the Dashboard or Mallmanac to open its workspace.

### Update phase information

Each phase contains task checkboxes and fields for:

- Task notes.
- Phase notes.
- Target date.
- Actual hours.

Select **Save** to store all changes in that phase. Hours accept half-hour
increments and are shown beside the phase estimate when one exists.

### Add documents and resources

In **Documents & Resources**:

1. Enter a label, such as `Setup Guide`.
2. Enter the SharePoint or other resource URL.
3. Select **Add link**.

Select **Remove** next to a link to delete it from the lab.

### Update ownership and course information

The record owner can be changed by the current owner, a Manager, or an Admin.
Select a user (or **Unassigned**) and choose **Change owner**.

The same users can set or update the **Course ID**. Ownership changes and
course-ID changes are recorded in the system log.

### View the calendar

Select **Calendar view** from a lab workspace. The calendar places phases on
their target dates and lists phases without a valid target date under
**Unscheduled**. Use the previous and next month controls to change the month.

## 7. Move a lab through the eight phases

Every lab follows this sequence:

1. Concept — completion
2. Design — approval required
3. Develop — approval required
4. Video Demo — completion
5. Testing & Feedback — approval required
6. Publish — completion
7. Production — approval required
8. Post-Production Acceptance — completion

Earlier phases must be finished before a later phase can start. Completing a
phase automatically unlocks the next one.

### Completion phases

For a completion phase:

1. Select **Start phase**.
2. Complete and save the tasks and notes.
3. Select **Mark completed**.

No Manager approval is required.

### Approval phases

For an approval phase:

1. Select **Start phase**.
2. Complete and save the tasks, notes, target date, and hours.
3. Select **Submit for approval**.
4. A Manager reviews the work and selects **Approve**. The Manager can add an
   optional approval note.

While the phase is waiting, non-Managers see **Awaiting manager approval**.
Managers can approve from the lab workspace or the Dashboard queue.

### Block and unblock a phase

Select **Block** when work cannot continue. A blocked phase remains visible and
prevents normal progression. Select **Unblock** when work can resume, then
continue the phase workflow.

## 8. Use the Mallmanac

The Mallmanac shows every active lab as an eight-column lifecycle map:
Development phases appear first, followed by Production phases.

- A check mark indicates a completed task.
- The location pin marks the furthest completed task.
- Select a lab name to open its workspace.

### Time Warp (Admins only)

Time Warp is for recording work that was completed before the lab was entered
in HOLO. It is not a shortcut for skipping current review.

1. Open **Mallmanac**.
2. Turn on **Time Warp mode**.
3. Select the task pill representing the lab's actual historical position.
4. Confirm the action.

HOLO marks earlier phases complete, auto-approves earlier approval phases, and
checks tasks up to the selected task. The selected phase remains open so it can
still follow its normal approval or completion workflow. Time Warp is
forward-only, cannot be undone from the Mallmanac, and does not send
notification emails.

## 9. Staff administration

Managers and Admins can open **Admin**.

### Invite users

1. Enter the person's email address.
2. Choose **Member**, **Manager**, or **Admin**.
3. Select **Generate link**.
4. Copy the generated link and send it securely, or select **Email this link**
   when the mail forwarder is configured.

Pending invitations show their role and expiration date. Invitation links are
single-use.

### Reset a password

In the **Users** section, select **reset password** for the account. HOLO shows
a temporary password once. Share it securely with the user; they must change it
at their next login.

### Archive and restore a lab

Select **Archive a lab** to hide a lab from the Dashboard and Mallmanac without
deleting its data. Select **View archived** to find archived labs and
**Unarchive** a lab to return it to the active portfolio.

### Back up and restore the database

The **Database backup** section creates and lists database backups.

- Select **Back up now** for an immediate backup.
- Select **download** to save a backup file elsewhere.
- Select **restore** beside an existing backup, or upload a downloaded `.db`
  file and choose **Restore from file**.

Restoring replaces the current database. HOLO validates the file and creates a
safety backup first. You may need to sign in again after a restore. Keep an
off-server copy of important backups.

### Review the system log

The **System Log** records state-changing actions, including logins, lab and
phase changes, invitations, password resets, backups, restores, and
notification configuration changes. Use the filters and pagination to
investigate activity.

## 10. Notifications (Managers and Admins)

Open **Notifications** to configure phase email notifications.

1. In **Mail forwarder**, enter the SMTP relay host, port, From address, and
   optional default recipient.
2. Enter the **App base URL** if email links need a specific public URL.
3. Enable the forwarder and select **Save forwarder**.
4. Use **Send test email** to verify delivery.
5. Create a notification list.
6. Add recipient email addresses to the list.
7. Add subscriptions by choosing a phase and event:
   `submitted`, `approved`, or `completed`.

Notifications are best-effort. A mail delivery failure does not stop a phase
from advancing.

## 11. Statuses and progress

Phase statuses have these meanings:

- **Not started** — locked or ready to begin.
- **In progress** — actively being worked.
- **Awaiting approval** — submitted and waiting for a Manager.
- **Approved** — an approval phase passed its gate.
- **Completed** — a completion phase or approved phase is finished.
- **Blocked** — work is paused until it is unblocked.

The lab status and percentage on the Dashboard summarize these phase states.

## 12. Troubleshooting

### I cannot sign in

- Confirm that you are using the email address associated with your HOLO
  account.
- Check capitalization and password spelling.
- If your account was reset, use the temporary password and complete the
  required password change.
- Ask a staff member to confirm that your invitation was used and has not
  expired.

### The next phase is locked

Open the previous phase and confirm that it is **Approved** or **Completed**.
Blocked or awaiting-approval phases must be resolved before the next phase can
start.

### I cannot approve a phase

Only users with the **Manager** role can approve submissions. Admins manage the
system but do not hold the approval gate.

### A notification was not delivered

Ask a Manager or Admin to check that the forwarder is enabled, the relay host
and port are correct, recipients are present, and the subscription matches the
phase event. Use **Send test email** to isolate mail configuration issues.
