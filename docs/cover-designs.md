# Ready-made cover designs

Customers choose an occasion, then a size, then a cover from a gallery
filtered to that occasion. This is how you put designs in that gallery.

Designs are **content, not code**: adding, renaming and retiring one is a
command on the server, never a deploy.

## What to draw

| | |
|---|---|
| **Size** | **1937 × 2858 px** — 164 × 242 mm at 300 dpi |
| Minimum accepted | 1600 × 2360 px (below this it prints soft and is refused) |
| Format | PNG or JPEG, sRGB |

The file is the **front of the book plus the turn-in** that folds around the
board. It is *not* the whole wrap — the back panel and the spine are printed
in a flat colour you choose, which is what lets one file work for all four
book sizes. Only the spine width changes between sizes, and the spine is not
in your file.

**The turn-in is on three sides, not four.** The left edge of your file is
the spine fold: nothing is lost there, and the visible panel sits flush
against it. The seen area is therefore *not* centred in the file.

```
    x=0                                     x=148mm      x=164mm
    │                                          │            │
    ├──────────────── 1937 px (164 mm) ─────────────────────┤
 y=0┌───────────────────────────────────────────────────────┐ ┐
    │ ▓▓▓▓▓▓▓▓▓ 16 mm — folds out of sight ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ │ │
    ├───────────────────────────────────────────┬───────────┤ │
    │                                           │▓▓▓▓▓▓▓▓▓▓▓│ │
    │      148 × 210 mm — what is seen on       │▓ 16 mm  ▓▓│ 2858 px
    │      the closed book. Flush LEFT.         │▓ folds  ▓▓│ (242 mm)
    │                                           │▓ away   ▓▓│ │
    ├───────────────────────────────────────────┴───────────┤ │
    │ ▓▓▓▓▓▓▓▓▓ 16 mm — folds out of sight ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ │ │
    └───────────────────────────────────────────────────────┘ ┘
    ↑ spine fold: visible, nothing trimmed          y=226mm ↑
```

Three rules:

1. **16 mm folds out of sight on the top, bottom and right — nothing on the
   left.** Let the background bleed off those three edges; put nothing there
   you need to keep. Art at the very left edge *does* survive.
2. **Keep text and faces 21 mm inside the top, bottom and right edges**
   (16 mm turn-in + 5 mm safe margin) and **5 mm inside the left**. The
   guillotine has about ±1 mm of play.
3. **Pick a back/spine colour that belongs with the art** — usually the
   design's darkest or most common tone.

If you centre your subject in the *file* it will sit 8 mm off-centre on the
printed cover. Centre it in the 148 × 210 mm panel instead: that is
x = 74 mm from the left edge of the file, y = 121 mm from the top.

**`cover-artwork-guide.png`** in this folder is the same thing as a layer:
1937 × 2858 px with transparency, red over everything the turn-in eats, the
visible panel and the safe area outlined, and the true centre marked. Drop it
on top of a draft in any editor to check the framing before uploading.

A design can either leave a window for the customer's photo, or be a
complete cover with no photo at all. Both work; say which with
`--photo-rect`.

## Adding a design — the console

Go to **`https://your-domain/admin/`** and sign in with `ADMIN_TOKEN` from the
server's `.env`. Then **+ New**, choose the artwork file, and fill in the form.

The console exists for one reason above all: you **drag** the photo window
and the title over the real artwork and watch where they land, instead of
guessing `19,24,110,110` and finding out at print time. Everything you see
in that preview — the framing, the safe margin, the automatic title ink — is
computed the same way the print renderer computes it.

**Artwork with its own lettering:** untick *"The customer can put a title on
this design"* and the design ships with no title box. The customer gets the
cover exactly as you drew it, and nothing is printed over your type. Tick it
back on and the title returns — it is a setting, not a one-way door.

Two things the console does that the command line cannot:

- It warns you *before upload* if the file is too small or the wrong shape.
- **Save** on an existing design updates it without re-uploading the artwork,
  so nudging a photo window costs nothing.

If `ADMIN_TOKEN` is empty on the server, sign-in always fails — that is the
switch that keeps the admin API off entirely.

## Adding a design — the command line

Still there, and still the same validation, for scripting or when you are
already in an SSH session. From `backend/`:

```bash
python scripts/cover_design.py add romance-gold ~/art/romance-gold.png \
    --name "Gold hearts" \
    --types love,birthday \
    --photo-rect 19,24,110,110 \
    --title 74,158,24 \
    --title-color '#ffffff' \
    --bg '#7a2740' \
    --order 10
```

| Option | Meaning |
|---|---|
| `slug` | Stable handle, e.g. `romance-gold`. Customers never see it. |
| `--name` | Shown under the thumbnail in the gallery. |
| `--types` | Occasions this design suits: `love`, `travel`, `birthday`, `memory`. **Leave it out and the design appears for every occasion.** |
| `--photo-rect x,y,w,h` | Where the customer's photo goes, in mm from the top-left of the 148 × 210 front panel. **Leave it out for a complete artwork cover.** |
| `--title x,y[,size]` | Where the title sits, in mm; size in points. **Leave it out for artwork that already carries its own lettering** — the customer then gets no title box at all. |
| `--title-color` | `#rrggbb`. Leave it out and it is chosen automatically. |
| `--bg` | Back panel and spine colour. |
| `--order` | Sort position in the gallery — lower comes first. |

`python scripts/cover_design.py spec` prints the same specification, so you
never have to look it up here.

## Managing the gallery

In the console: click a design to edit it, tick **Visible** off (or press
**Retire**) to take it out of the gallery. Retired designs stay in the list
with a `RETIRED` badge so you can put them back.

The same from the command line:

```bash
python scripts/cover_design.py list                 # everything visible
python scripts/cover_design.py list --type love     # what a love-story customer sees
python scripts/cover_design.py list --all           # including retired
python scripts/cover_design.py retire romance-gold  # remove from the gallery
python scripts/cover_design.py restore romance-gold
```

Two things worth knowing:

- **Re-running `add` with the same slug replaces that design in place.** That
  is how you correct one — it never leaves a second copy in the gallery.
- **Retiring never breaks a book already using the design.** Books that have
  been ordered keep their artwork and keep printing exactly as the customer
  confirmed; the design simply stops being offered to new customers.

## Checking a design before you offer it

Add it, open the editor (the console has an **Open editor** link), pick that
occasion, and choose the design. What you
see on the cover is what prints — the editor, the preview and the print file
all place the artwork by the same rule.

Order one physical test book before offering a design to customers. Screen
colour and printed colour are not the same thing, and the turn-in is
impossible to judge on a screen.

## Limitations to be aware of

- **One artwork per design, front only.** If you want art wrapping across the
  spine onto the back, that needs a file per book size (the spine width
  changes) and is not built yet — say the word.
- **Names are not translated.** The gallery shows the `--name` you give,
  in that one language, to every customer. Thumbnails carry most of the
  meaning, so this is usually fine; if it matters, keep names short and
  neutral, or use the occasion to do the talking.
