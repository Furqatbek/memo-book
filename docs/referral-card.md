# Referral card — CR-003-4

**No code.** This is a printing job and a spreadsheet. Deliberately so: at
40 books a month a referral system is a database table nobody reads, and
the thing that actually works is a piece of card in the box.

Revisit building anything only past roughly 30 orders a month.

---

## What to print

50 cards. Business-card size, **90 × 50 mm**, printed on the same stock as
the book's endpapers if the printer has offcuts — it costs nothing and the
card feels like part of the book rather than a flyer.

One side only. The code is written **by hand**, in pen, at packing time.
That is not laziness: a handwritten code is what makes it obviously from a
person, and it means no two boxes can accidentally carry the same code.

### English

> **Know someone with too many photos?**
>
> Give them 10% off — and get 10% off your next book.
>
> Your code: ⟨ handwritten ⟩
>
> rspixel.uz · Telegram @Eurohand1

### Russian

> **Знаете кого-то, у кого слишком много фотографий?**
>
> Подарите им 10% скидки — и получите 10% на свою следующую книгу.
>
> Ваш код: ⟨ от руки ⟩
>
> rspixel.uz · Telegram @Eurohand1

### Uzbek (Latin)

> **Suratlari juda koʻp tanishingiz bormi?**
>
> Ularga 10% chegirma bering — va keyingi kitobingizga 10% oling.
>
> Sizning kodingiz: ⟨ qoʻlda ⟩
>
> rspixel.uz · Telegram @Eurohand1

**Which language to print:** Russian and Uzbek Latin, 25 each, both sides
of the same card if the printer allows. Karakalpak and Cyrillic are not
worth a separate run at 50 cards — write the code by hand and the language
of the card matters less than the fact that somebody wrote in it.

---

## How the code works

Format: **initials + order number**, e.g. `AK-1042`. Readable aloud over
the phone, which is how it will actually be passed on.

The customer gives the code to a friend. The friend mentions it when they
order — in the Telegram chat or on the phone. The operator applies 10% by
hand and writes both lines in the sheet.

## The spreadsheet

Five columns, nothing more:

| Code | Issued to (order) | Issued on | Redeemed by (order) | Discount given to issuer |
|---|---|---|---|---|

The last column is the one that gets forgotten. **The promise is two
discounts, not one** — the friend's order and the issuer's next one. A
referral programme that quietly only honours the first half is worse than
none, because the person it cheats is a customer who liked you enough to
recommend you.

## When to stop doing it by hand

Past ~30 orders a month, or the first time you cannot answer "has this
code already been used?" in under a minute. Until then the spreadsheet is
faster than anything that could be built, and it fails visibly rather than
silently.
