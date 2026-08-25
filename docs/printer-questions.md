# Technical questions for the printer

Every answer below maps to a configuration value or a render decision in
the backend — collect them **before** the first customer order. The
existing lay-flat spec and quote-request letter is in
[`printer-rfq.md`](printer-rfq.md); this list is the follow-up needed to
produce correct print files. The Russian version is below —
русская версия ниже.

**Product recap:** A5 portrait photo book, 148×210 mm trim, lay-flat
hardcover. The customer buys **sheets of paper**, printed on both sides:
16 / 32 / 48 / 96 sheets, which is 32 / 64 / 96 / 192 printed pages. We
deliver two PDFs per order: a multi-page interior PDF and a one-sheet
cover-wrap PDF.

> **If you can only answer three, answer these.** Everything else we can
> work around; these three we cannot guess, and a wrong guess is a wasted
> print run:
>
> - **Q1** — spine width per size, in **sheets**
> - **Q2** — turn-in (wrap) margin
> - **Q13** — safe margin near the bound edge for lay-flat
>
> The numbers we use today are placeholders taken from the spec, not from
> any real press. Nothing goes to production until you replace them.

## 1. Cover geometry — blocks production (config `SPINE_MM_*`, `WRAP_MM`)

1. **Spine width in mm for each size — 16, 32, 48 and 96 SHEETS**
   (= 32, 64, 96 and 192 printed pages) — with the exact paper you'll
   print the interior on. If it depends on paper choice, give the formula
   (mm per sheet + board allowance). Please answer in sheets: our current
   placeholders were written against page counts and are certainly wrong
   for the 48- and 96-sheet books.
2. **Turn-in (wrap) margin** for the hardcover: how many mm of printed
   cover must extend past the board on each side? (We currently assume
   16 mm.)
3. Any **hinge/groove allowance** next to the spine we must keep free of
   text?
4. **Board thickness** you bind with (affects the wrap sheet size).
5. Our cover file is **one flat sheet**: [wrap][back 148][spine][front
   148][wrap] wide × [wrap][210][wrap] high, art extending through the
   wrap. Does that match your workflow, or do you need another imposition?

## 2. Colour — decides RGB vs CMYK pipeline (config `RENDER_COLOR_MODE`, `ICC_PROFILE_PATH`)

6. Do you accept **RGB (sRGB) PDFs** and convert on your end, or do you
   require **CMYK**?
7. If CMYK: **which ICC profile** should we convert with (send us the
   file), and what **total ink limit**?
8. Do you apply any automatic colour "enhancement" we should disable?

## 3. Interior file format

9. We deliver a single PDF, **one page per PDF page**, size 154×216 mm
   (148×210 trim + **3 mm bleed** on all sides), images at 300 dpi. OK,
   or do you need a different bleed, spreads, or imposition?
10. Do you need **trim/crop marks**, or clean pages with bleed only?
11. Is there a **maximum file size** / preferred delivery channel for
    ~60–150 MB files (email, Telegram, portal, USB)?
12. For lay-flat binding, are pages printed as **single leaves or
    spreads**? Does the first interior page sit on the right?
13. Minimum **safe margin** from trim for text (we keep 5 mm) — enough,
    or do you recommend more near the gutter for lay-flat? The editor
    currently warns customers off a **5 mm strip along the bound edge**
    of every page; tell us your figure and we will match it.

## 4. Paper and finishing

14. Interior paper options (weight, coating) and which you recommend for
    photo books; does the choice change the spine table from Q1?
15. Cover finishing options: matte/gloss lamination, and the price
    difference.

## 5. Process and commercial

16. Cost and turnaround for a **single test book** (we will order one
    before any customer order) at **16 sheets** and at **96 sheets** — the
    smallest and largest books we sell.
17. Per-unit price at quantities 1 / 10 / 50 for each of the four sheet
    sizes, and standard turnaround per order.
18. What do you **check before printing** (preflight)? What happens on a
    binding/colour defect — whose reprint?
19. Pickup/delivery logistics within Tashkent and to regions.

---

# Технические вопросы типографии (RU)

> **Если ответите только на три вопроса — ответьте на эти.** Остальное мы
> обойдём; эти три угадать невозможно, а ошибка означает испорченный тираж:
>
> - **п. 1** — ширина корешка по объёмам, **в листах**
> - **п. 2** — загиб (клапан) обложки
> - **п. 13** — безопасный отступ у корешка для lay-flat
>
> Цифры, которые стоят у нас сейчас, — ориентировочные, из техзадания, а не
> с реальной машины. В производство ничего не уйдёт, пока вы их не замените.

**О продукте:** фотокнига A5 портретная, обрезной формат 148×210 мм,
твёрдая обложка с раскрытием lay-flat (на 180°). Клиент выбирает
количество **листов** бумаги с двусторонней печатью: 16 / 32 / 48 / 96
листов, то есть 32 / 64 / 96 / 192 печатные страницы. На каждый заказ мы
передаём два PDF: многостраничный блок и обложку одним разворотом.

## 1. Геометрия обложки — блокирует производство

1. **Ширина корешка в мм для каждого объёма — 16, 32, 48 и 96 ЛИСТОВ**
   (= 32, 64, 96 и 192 печатные страницы) — на той бумаге, на которой
   будет печататься блок. Если зависит от бумаги — дайте формулу (мм на
   лист + допуск на картон). Просим ответить именно в листах: наши текущие
   ориентировочные значения записаны по страницам и для книг на 48 и 96
   листов заведомо неверны.
2. **Загиб (клапан) обложки**: сколько мм запечатанной обложки должно
   заходить за картон с каждой стороны? (Сейчас закладываем 16 мм.)
3. Есть ли **биговка/шарнир** у корешка, где нельзя размещать текст?
4. **Толщина переплётного картона.**
5. Наш файл обложки — **один плоский лист**: [загиб][задняя 148]
   [корешок][передняя 148][загиб] в ширину × [загиб][210][загиб] в
   высоту, изображение продолжается на загибы. Подходит ли такой макет,
   или нужен другой спуск?

## 2. Цвет

6. Принимаете ли **RGB (sRGB) PDF** с конверсией на вашей стороне, или
   обязателен **CMYK**?
7. Если CMYK: **какой ICC-профиль** использовать (пришлите файл) и какой
   **лимит суммарного красконаложения**?
8. Применяете ли автоматическое «улучшение» цвета, которое нужно
   отключить?

## 3. Файл блока

9. Мы передаём один PDF, **одна страница книги = одна страница PDF**,
   размер 154×216 мм (148×210 + **вылеты 3 мм** со всех сторон),
   изображения 300 dpi. Подходит, или нужны другие вылеты, развороты,
   спуск полос?
10. Нужны ли **метки реза**, или достаточно чистых страниц с вылетами?
11. **Максимальный размер файла** и удобный канал передачи для файлов
    60–150 МБ (почта, Telegram, портал, флешка)?
12. Для lay-flat переплёта страницы печатаются **отдельными листами или
    разворотами**? Первая страница блока — справа?
13. Минимальный **безопасный отступ** текста от реза (мы держим 5 мм) —
    достаточно, или у корешка для lay-flat нужно больше? Редактор сейчас
    предупреждает клиента о **полосе 5 мм вдоль корешка** на каждой
    странице; сообщите вашу цифру — приведём в соответствие.

## 4. Бумага и отделка

14. Варианты бумаги блока (плотность, покрытие) и что вы рекомендуете для
    фотокниг; меняет ли выбор бумаги таблицу корешков из п. 1?
15. Отделка обложки: матовая/глянцевая ламинация и разница в цене.

## 5. Процесс и коммерция

16. Стоимость и срок **одного тестового экземпляра** (закажем до первого
    клиентского заказа) на **16 листов** и на **96 листов** — это самая
    тонкая и самая толстая книга в нашей линейке.
17. Цена за экземпляр при тиражах 1 / 10 / 50 по каждому из четырёх
    объёмов и стандартный срок изготовления.
18. Что вы **проверяете перед печатью** (префлайт)? Как решается брак
    переплёта/цвета — за чей счёт перепечатка?
19. Логистика: самовывоз/доставка по Ташкенту и в регионы.

---

# Cover message — paste into Telegram / e-mail

Send the questionnaire as an attachment (or a link) with a short note; a
wall of nineteen questions with no framing usually gets no reply at all.
Replace `[…]` with your own details before sending.

## Russian

> Здравствуйте! Меня зовут `[имя]`, я запускаю сервис фотокниг RS Pixel
> (rspixel.uz) в Ташкенте. Клиент собирает книгу на сайте, а мы передаём
> вам готовые PDF — блок и обложку.
>
> Формат: A5 портретная, 148×210 мм в обрез, твёрдая обложка lay-flat.
> Объёмы: 16 / 32 / 48 / 96 листов с двусторонней печатью.
>
> Прикладываю технические вопросы. Если целиком отвечать долго — самое
> важное это три пункта: **ширина корешка по объёмам (в листах)**,
> **загиб обложки в мм** и **безопасный отступ у корешка**. Без них мы не
> можем собрать корректный файл обложки.
>
> Отдельно интересует стоимость и срок **одного тестового экземпляра** —
> хочу напечатать один и проверить, прежде чем брать заказы у клиентов.
>
> Спасибо! `[имя]`, `[телефон]`

## Uzbek

> Assalomu alaykum! Mening ismim `[ism]`, Toshkentda RS Pixel
> (rspixel.uz) fotokitob xizmatini ishga tushiryapman. Mijoz kitobni
> saytda yigʻadi, biz sizga tayyor PDF — blok va muqova — yuboramiz.
>
> Format: A5, kesimda 148×210 mm, lay-flat qattiq muqova. Hajmlari:
> ikki tomonlama bosiladigan 16 / 32 / 48 / 96 varaq.
>
> Texnik savollarni ilova qilyapman. Hammasiga javob berish uzoq boʻlsa,
> eng muhimi uchtasi: **hajmlar boʻyicha gʻilof (koreshok) qalinligi —
> varaqda**, **muqova qayrimasi necha mm** va **koreshok yonidagi xavfsiz
> chekka**. Ularsiz toʻgʻri muqova fayli yigʻilmaydi.
>
> Alohida: **bitta sinov nusxasi** narxi va muddati qanday? Mijozlardan
> buyurtma olishdan oldin bittasini chiqarib koʻrmoqchiman.
>
> Rahmat! `[ism]`, `[telefon]`

## What to do with the answers

| Answer | Goes into |
|---|---|
| Q1 spine per sheet tier | `SPINE_MM_16/32/48/96` in `deploy/.env` |
| Q2 turn-in margin | `WRAP_MM` in `backend/app/render/cover.py` |
| Q13 gutter safe margin | the editor's bound-edge warning strip |
| Q6/Q7 colour | `RENDER_COLOR_MODE`, `ICC_PROFILE_PATH` |
| Q10 crop marks | render option (currently omitted) |
| Q17 per-unit price | `PRICE_MINOR_*`, then `PRICES_CONFIRMED=true` (A74) |

Until Q1, Q2 and Q13 come back, `SPINE_MM_*` and `WRAP_MM` are the spec's
placeholder numbers and no cover should be sent to production. Until Q17
comes back, `PRICES_CONFIRMED` stays false and checkout refuses — which is
the intended state, not a bug.
