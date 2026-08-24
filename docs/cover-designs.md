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

```
      ┌──────────────── 1937 px (164 mm) ────────────────┐
      │  ← 16 mm turn-in: folds out of sight →           │  ┐
      │   ┌───────────────────────────────────────────┐  │  │
      │   │                                           │  │  │
      │   │        148 × 210 mm — what is seen        │  │  2858 px
      │   │        on the closed book                 │  │  (242 mm)
      │   │                                           │  │  │
      │   └───────────────────────────────────────────┘  │  │
      │                                                  │  ┘
      └──────────────────────────────────────────────────┘
```

Three rules:

1. **16 mm all round folds out of sight.** Let the background run to the
   edge; put nothing there you need to keep.
2. **Keep text and faces 21 mm inside every edge** (16 mm turn-in + 5 mm safe
   margin). The guillotine has about ±1 mm of play.
3. **Pick a back/spine colour that belongs with the art** — usually the
   design's darkest or most common tone.

A design can either leave a window for the customer's photo, or be a
complete cover with no photo at all. Both work; say which with
`--photo-rect`.

## Adding a design

On the server, from `backend/`:

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
| `--title x,y[,size]` | Where the title sits, in mm; size in points. |
| `--title-color` | `#rrggbb`. Leave it out and it is chosen automatically. |
| `--bg` | Back panel and spine colour. |
| `--order` | Sort position in the gallery — lower comes first. |

`python scripts/cover_design.py spec` prints the same specification, so you
never have to look it up here.

## Managing the gallery

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

Add it, open the editor, pick that occasion, and choose the design. What you
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
