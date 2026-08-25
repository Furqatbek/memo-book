# The admin console

`https://your-domain/admin/` — two sections: **Orders** (the daily job) and
**Cover designs** (see [`cover-designs.md`](cover-designs.md)).

## Turning it on

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put it in the server's `.env` as `ADMIN_TOKEN`, redeploy, sign in with it.

**An empty `ADMIN_TOKEN` switches the whole admin API off** — every route
answers 404, as if it were never there. That is on purpose: forgetting to set
it must fail closed, not leave a door open on a public domain. If sign-in
always fails, that is the first thing to check.

Changing `ADMIN_TOKEN` and restarting is how you revoke access.

## Orders — the daily round

The list opens on **Open**: everything that still needs something doing.
Delivered, cancelled and refunded orders drop out of it; switch to **All** to
find them again. Search takes a reference, a name, or a phone number — the
phone match ignores spaces, `+` and dashes, so type it however you like.

Click an order and you get the customer, the print files, the history, and a
row of buttons for what can happen next. **Those buttons come from the
server**, which works them out from the order's actual state — so you can
never be offered a step that would be refused.

### When a transfer arrives

An order sits at **Waiting for payment** until you say the money came in.
Open it, put something useful in the note (`transfer seen 12:04`), and press
**The transfer arrived — mark paid**.

That does everything a real card provider's callback would: the book locks,
the print files are made, and the printer gets the Telegram message. Pressing
it twice is safe — it will not print the book twice.

> If `AUTO_CONFIRM_ORDERS=true` (the current pilot setting), orders confirm
> themselves at checkout and you will not see this button. You still verify
> the transfer; you just do it while the files are already being made, and
> **Cancel order** is how you undo one that never paid.

### Handing it to the printer

Once the files exist you get **Interior PDF** and **Cover PDF** links, good
for seven days. They are for you and the printer — customers never get them.
**Send to the printer again** re-queues the Telegram message if it went
missing.

Then walk the order along as it happens: **Sent to the printer** →
**Shipped** → **Delivered**. Every press is recorded in the history with your
note, so you can always see what happened and when.

### Cancelling and refunding

**Cancel order** unlocks the book so the customer can edit or re-order it. It
does **not** move any money — if they paid, refund them yourself, then record
it with **Refunded**.

There is no way to delete an order. The history is the record of what
happened to someone's money, and it stays.

## What the console cannot do

Deliberately:

- **Delete anything.** Orders are retired through the state machine; cover
  designs are retired, never removed, so books already using them keep
  printing.
- **Force a status.** Only transitions the state machine allows are offered,
  and only ones a person should be driving — the render states belong to the
  worker.
- **Move money.** Nothing here talks to a bank. Confirming a payment records
  what you saw; refunding records what you did.

## If something goes wrong

**"Print files failed"** — press **Try the print files again**. If it keeps
failing, the book itself is the problem, not the printer; the server logs
name the page.

**Sign-in fails with the right token** — check `ADMIN_TOKEN` is actually set
in the running container (`docker compose exec api env | grep ADMIN`), not
just in the `.env` on disk.

**The command line still works** for everything here, if you are already in
an SSH session: `scripts/confirm_payment.py`, `scripts/order_status.py`,
`scripts/artifacts.py`, `scripts/cover_design.py`. They share the same code
paths, so the two can never disagree.
