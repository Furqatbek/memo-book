"""Seasonal landing pages — P2-1.

The main page is travel-locked: "Your trip. Your photos. Your book." Every
headline frames the product as a travel book, and the next campaign is New
Year gifting, which is family, year-in-review and children. A visitor who
clicks a New Year ad and lands on "Your trip" has been told, in the first
second, that they are in the wrong place.

So the travel page stays exactly as it is — it is good BECAUSE it is
specific — and each campaign gets its own page with a matched headline,
matched samples and the same CTA. Ads point at the matching page.

WHY THIS IS GENERATED. Ten pages (two occasions x five languages) written
out by hand would be ten more files for every future copy fix to reach:
P1-1, P1-5 and P1-6 each had to touch five, and this would make it fifteen.
The copy lives in the tables below, the markup lives in one template, and
`tests/test_landing_pages.py` fails if the committed HTML and this script
have drifted apart. Regenerate with:

    cd backend && .venv/bin/python scripts/build_landings.py

Nothing about the shipped site changes: what is served is still plain
static HTML with no build step in front of it.

WHAT THE SAMPLES ARE. Drawings, labelled "Sample", exactly like the ones
on the main page. No book has been printed yet, so there is no photograph
of one to show, and a rendered mock-up passed off as a product photograph
would be the reviews problem in picture form. The day a real book exists,
these get replaced with photographs of it.
"""
import argparse
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
SITE = "https://rspixel.uz"

# The one date on these pages that is a promise rather than a fact. It is
# derived from the site's own "about 30 days from payment to delivery" with
# roughly a week of slack for the post, and it MUST be checked against the
# printer's December load before any money is spent pointing ads here — a
# December queue is not a November queue.
NEW_YEAR_ORDER_BY = {
    "en": "25 November",
    "ru": "25 ноября",
    "uz": "25-noyabr",
    "uz-cyrl": "25-ноябр",
    "kaa": "25-noyabr",
}

# lang: (directory under the site root, og:locale, hreflang, native name)
LANGS = {
    "en": ("", "en_GB", "en", "English"),
    "ru": ("ru/", "ru_RU", "ru", "Русский"),
    "uz": ("uz/", "uz_UZ", "uz", "Oʻzbekcha"),
    "uz-cyrl": ("uz-cyrl/", "uz_Cyrl_UZ", "uz-Cyrl", "Ўзбекча"),
    "kaa": ("kaa/", "kaa_UZ", "kaa", "Qaraqalpaqsha"),
}

# Everything that does not change between occasions.
CHROME = {
    "en": {
        "skip": "Create your book",
        "how_eyebrow": "How it works",
        "how_title": "From camera roll to hardcover",
        "steps": [
            ("Start with a blank book",
             "Open the editor and get an empty book — your pages, your rules."),
            ("Add your photos",
             "One by one or all at once. Auto-layout places them in the order "
             "they were taken, and you rearrange anything you like."),
            ("We print and deliver",
             "Pay online when you are happy. Your design goes to print exactly "
             "as you made it."),
        ],
        "samples_badge": "Sample",
        "cta_secondary": "See how it works",
        "hero_meta": "Free to design — you pay only when you order the printed book.",
        "band_body": "Start your book now — designing is free, and you only pay "
                     "when you order the print.",
        "full_site": "Everything about the book",
        "f_brand": "Design your photo book online. Printed in Uzbekistan.",
        "f_delivery": "We deliver anywhere in Uzbekistan.",
        "f_product": "Product",
        "f_support": "Support",
        "f_contacts": "Contacts",
        "f_language": "Language",
        "f_faq": "FAQ",
        "f_track": "Track an order",
        "f_reprint": "Reprint policy",
        "f_main": "The full site",
        "f_create": "Create your book",
        "f_bottom": "© RS Pixel · Made in Uzbekistan",
    },
    "ru": {
        "skip": "Создать книгу",
        "how_eyebrow": "Как это работает",
        "how_title": "От галереи в телефоне до твёрдой обложки",
        "steps": [
            ("Начните с пустой книги",
             "Откройте редактор — получите пустую книгу. Ваши страницы, ваши правила."),
            ("Добавьте фотографии",
             "По одной или все сразу. Автозаполнение расставит их в том порядке, "
             "в каком вы снимали, а дальше меняйте как угодно."),
            ("Мы печатаем и доставляем",
             "Оплатите онлайн, когда всё готово. Макет уходит в печать ровно "
             "таким, каким вы его сделали."),
        ],
        "samples_badge": "Образец",
        "cta_secondary": "Как это работает",
        "hero_meta": "Создавать бесплатно — платите только за печать.",
        "band_body": "Начните прямо сейчас — создание бесплатно, платите только "
                     "при заказе печати.",
        "full_site": "Всё о книге",
        "f_brand": "Создайте свою фотокнигу онлайн. Напечатано в Узбекистане.",
        "f_delivery": "Доставляем в любую точку Узбекистана.",
        "f_product": "Продукт",
        "f_support": "Поддержка",
        "f_contacts": "Контакты",
        "f_language": "Язык",
        "f_faq": "Вопросы и ответы",
        "f_track": "Отследить заказ",
        "f_reprint": "Перепечатка",
        "f_main": "Основной сайт",
        "f_create": "Создать книгу",
        "f_bottom": "© RS Pixel · Сделано в Узбекистане",
    },
    "uz": {
        "skip": "Kitob yaratish",
        "how_eyebrow": "Qanday ishlaydi",
        "how_title": "Telefondagi galereyadan qattiq muqovagacha",
        "steps": [
            ("Boʻsh kitobdan boshlang",
             "Muharrirni oching — boʻsh kitob olasiz. Sizning sahifalaringiz, "
             "sizning qoidalaringiz."),
            ("Suratlaringizni qoʻshing",
             "Bittalab yoki hammasini birdan. Avtomatik joylashtirish ularni siz "
             "olgan tartibda joylaydi, keyin xohlaganingizcha oʻzgartirasiz."),
            ("Biz chop etamiz va yetkazamiz",
             "Hammasi tayyor boʻlgach onlayn toʻlang. Dizayningiz siz yaratgan "
             "koʻrinishda chop etiladi."),
        ],
        "samples_badge": "Namuna",
        "cta_secondary": "Qanday ishlaydi",
        "hero_meta": "Yaratish bepul — faqat chop etishga buyurtma berganingizda toʻlaysiz.",
        "band_body": "Hoziroq boshlang — yaratish bepul, faqat chop etishga "
                     "buyurtma berganingizda toʻlaysiz.",
        "full_site": "Kitob haqida hammasi",
        "f_brand": "Fotokitobingizni onlayn yarating. Oʻzbekistonda chop etilgan.",
        "f_delivery": "Oʻzbekistonning istalgan nuqtasiga yetkazib beramiz.",
        "f_product": "Mahsulot",
        "f_support": "Yordam",
        "f_contacts": "Aloqa",
        "f_language": "Til",
        "f_faq": "Savol-javob",
        "f_track": "Buyurtmani kuzatish",
        "f_reprint": "Qayta chop etish",
        "f_main": "Asosiy sayt",
        "f_create": "Kitob yaratish",
        "f_bottom": "© RS Pixel · Oʻzbekistonda yaratilgan",
    },
    "uz-cyrl": {
        "skip": "Китоб яратиш",
        "how_eyebrow": "Қандай ишлайди",
        "how_title": "Телефондаги галереядан қаттиқ муқовагача",
        "steps": [
            ("Бўш китобдан бошланг",
             "Муҳаррирни очинг — бўш китоб оласиз. Сизнинг саҳифаларингиз, "
             "сизнинг қоидаларингиз."),
            ("Суратларингизни қўшинг",
             "Битталаб ёки ҳаммасини бирдан. Автоматик жойлаштириш уларни сиз "
             "олган тартибда жойлайди, кейин хоҳлаганингизча ўзгартирасиз."),
            ("Биз чоп этамиз ва етказамиз",
             "Ҳаммаси тайёр бўлгач онлайн тўланг. Дизайнингиз сиз яратган "
             "кўринишда чоп этилади."),
        ],
        "samples_badge": "Намуна",
        "cta_secondary": "Қандай ишлайди",
        "hero_meta": "Яратиш бепул — фақат чоп этишга буюртма берганингизда тўлайсиз.",
        "band_body": "Ҳозироқ бошланг — яратиш бепул, фақат чоп этишга "
                     "буюртма берганингизда тўлайсиз.",
        "full_site": "Китоб ҳақида ҳаммаси",
        "f_brand": "Фотокитобингизни онлайн яратинг. Ўзбекистонда чоп этилган.",
        "f_delivery": "Ўзбекистоннинг исталган нуқтасига етказиб берамиз.",
        "f_product": "Маҳсулот",
        "f_support": "Ёрдам",
        "f_contacts": "Алоқа",
        "f_language": "Тил",
        "f_faq": "Савол-жавоб",
        "f_track": "Буюртмани кузатиш",
        "f_reprint": "Қайта чоп этиш",
        "f_main": "Асосий сайт",
        "f_create": "Китоб яратиш",
        "f_bottom": "© RS Pixel · Ўзбекистонда яратилган",
    },
    "kaa": {
        "skip": "Kitap jaratıw",
        "how_eyebrow": "Qalay isleydi",
        "how_title": "Telefondaǵı galereyadan qattı muqabaǵa shekem",
        "steps": [
            ("Bos kitaptan baslań",
             "Redaktordı ashıń — bos kitap alasız. Sizdiń betlerińiz, sizdiń "
             "qaǵıydalarıńız."),
            ("Súwretlerińizdi qosıń",
             "Bir-birlep yamasa hámmesin birden. Avtomatikalıq jaylastırıw olardı "
             "siz túsirgen tártipte jaylastıradı, keyin qálegenińizshe ózgertesiz."),
            ("Biz basıp shıǵaramız hám jetkeremiz",
             "Hámmesi tayar bolǵanda onlayn tóleń. Dizaynıńız siz jaratqan "
             "túrde basıp shıǵarıladı."),
        ],
        "samples_badge": "Úlgi",
        "cta_secondary": "Qalay isleydi",
        "hero_meta": "Jaratıw biypul — tek basıwǵa buyırtpa bergende tóleysiz.",
        "band_body": "Házir baslań — jaratıw biypul, tek basıwǵa buyırtpa "
                     "bergende tóleysiz.",
        "full_site": "Kitap haqqında hámmesi",
        "f_brand": "Fotokitabıńızdı onlayn jaratıń. Ózbekstanda basılǵan.",
        "f_delivery": "Ózbekstannıń qálegen jerine jetkerip beremiz.",
        "f_product": "Ónim",
        "f_support": "Járdem",
        "f_contacts": "Baylanıs",
        "f_language": "Til",
        "f_faq": "Sorawlar",
        "f_track": "Buyırtpanı gúzetiw",
        "f_reprint": "Qayta basıw",
        "f_main": "Tiykarǵı sayt",
        "f_create": "Kitap jaratıw",
        "f_bottom": "© RS Pixel · Ózbekstanda jaratılǵan",
    },
}

# Three flat palettes per occasion, used by the drawn sample cards.
PALETTES = {
    "new-year": [("#1a3fa0", "#8fb8ff"), ("#b8323c", "#f0a8a0"), ("#0f6b4a", "#e8b93c")],
    "family": [("#1c8a5a", "#cfe8d8"), ("#d97a2b", "#f6d9ab"), ("#7a4ea8", "#dcd0f0")],
}

OCCASIONS = {
    "new-year": {
        "en": {
            "title": "A photo book for New Year — RS Pixel",
            "desc": "Turn this year's photos into a real printed hardcover. Design "
                    "it yourself in a simple online editor; we print it and deliver "
                    "anywhere in Uzbekistan.",
            "kicker": "Online editor · Printed & shipped",
            "h1": "Your year. Your photos. Their New&nbsp;Year gift.",
            "lede": "A whole year of photographs is sitting on a phone where nobody "
                    "will ever look at them again. Turn them into a hardcover book — "
                    "you design it in an evening, we print it and deliver it "
                    "anywhere in Uzbekistan.",
            "timing_title": "Order by {order_by}",
            "timing_body": "Printing and delivery take about 30 days. Order by "
                           "{order_by} and your book should reach you comfortably "
                           "before 31 December. Later than that and we cannot "
                           "promise it arrives in time — we would rather say so now "
                           "than apologise in January.",
            "samples_title": "What a year looks like",
            "samples_lede": "Sample books designed in the editor — every page is "
                            "yours to change.",
            "captions": ["32 pages · A year with the children",
                         "48 pages · New Year at home",
                         "96 pages · The whole year, month by month"],
            "band_title": "A year of photos, in their hands",
        },
        "ru": {
            "title": "Фотокнига в подарок на Новый год — RS Pixel",
            "desc": "Превратите фотографии этого года в настоящую книгу в твёрдой "
                    "обложке. Сделайте её сами в простом онлайн-редакторе — мы "
                    "напечатаем и доставим в любую точку Узбекистана.",
            "kicker": "Онлайн-редактор · Печать и доставка",
            "h1": "Ваш год. Ваши фото. Их подарок на Новый&nbsp;год.",
            "lede": "Целый год фотографий лежит в телефоне, и больше их никто не "
                    "откроет. Соберите из них книгу в твёрдой обложке: вы делаете "
                    "её за вечер, мы печатаем и доставляем в любую точку "
                    "Узбекистана.",
            "timing_title": "Закажите до {order_by}",
            "timing_body": "Печать и доставка занимают около 30 дней. Закажите до "
                           "{order_by} — и книга придёт заметно раньше 31 декабря. "
                           "Позже этого срока мы не можем обещать, что успеем: "
                           "лучше сказать об этом сейчас, чем извиняться в январе.",
            "samples_title": "Как выглядит год",
            "samples_lede": "Образцы книг, сделанных в редакторе — любую страницу "
                            "можно изменить.",
            "captions": ["32 страницы · Год с детьми",
                         "48 страниц · Новый год дома",
                         "96 страниц · Весь год, месяц за месяцем"],
            "band_title": "Год фотографий — у них в руках",
        },
        "uz": {
            "title": "Yangi yilga fotokitob — RS Pixel",
            "desc": "Shu yilgi suratlaringizni haqiqiy qattiq muqovali kitobga "
                    "aylantiring. Oddiy onlayn muharrirda oʻzingiz yarating — biz "
                    "chop etamiz va Oʻzbekistonning istalgan nuqtasiga yetkazamiz.",
            "kicker": "Onlayn muharrir · Chop etish va yetkazish",
            "h1": "Sizning yilingiz. Sizning suratlaringiz. Ularning Yangi yil "
                  "sovgʻasi.",
            "lede": "Bir yillik suratlar telefonda yotibdi va ularni boshqa hech kim "
                    "ochmaydi. Ulardan qattiq muqovali kitob yigʻing: siz bir kechada "
                    "yaratasiz, biz chop etamiz va Oʻzbekistonning istalgan "
                    "nuqtasiga yetkazamiz.",
            "timing_title": "{order_by}gacha buyurtma bering",
            "timing_body": "Chop etish va yetkazish taxminan 30 kun oladi. "
                           "{order_by}gacha buyurtma bersangiz, kitob 31-dekabrdan "
                           "ancha oldin yetib keladi. Undan kechikkanda ulgurishimizni "
                           "vaʼda qila olmaymiz — yanvarda uzr soʻragandan koʻra "
                           "hozir aytganimiz maʼqul.",
            "samples_title": "Bir yil qanday koʻrinadi",
            "samples_lede": "Muharrirda yaratilgan namuna kitoblar — har bir sahifani "
                            "oʻzgartirish mumkin.",
            "captions": ["32 sahifa · Bolalar bilan oʻtgan yil",
                         "48 sahifa · Uydagi Yangi yil",
                         "96 sahifa · Butun yil, oyma-oy"],
            "band_title": "Bir yillik suratlar — ularning qoʻlida",
        },
        "uz-cyrl": {
            "title": "Янги йилга фотокитоб — RS Pixel",
            "desc": "Шу йилги суратларингизни ҳақиқий қаттиқ муқовали китобга "
                    "айлантиринг. Оддий онлайн муҳаррирда ўзингиз яратинг — биз "
                    "чоп этамиз ва Ўзбекистоннинг исталган нуқтасига етказамиз.",
            "kicker": "Онлайн муҳаррир · Чоп этиш ва етказиш",
            "h1": "Сизнинг йилингиз. Сизнинг суратларингиз. Уларнинг Янги йил "
                  "совғаси.",
            "lede": "Бир йиллик суратлар телефонда ётибди ва уларни бошқа ҳеч ким "
                    "очмайди. Улардан қаттиқ муқовали китоб йиғинг: сиз бир кечада "
                    "яратасиз, биз чоп этамиз ва Ўзбекистоннинг исталган "
                    "нуқтасига етказамиз.",
            "timing_title": "{order_by}гача буюртма беринг",
            "timing_body": "Чоп этиш ва етказиш тахминан 30 кун олади. "
                           "{order_by}гача буюртма берсангиз, китоб 31-декабрдан "
                           "анча олдин етиб келади. Ундан кечикканда улгуришимизни "
                           "ваъда қила олмаймиз — январда узр сўрагандан кўра "
                           "ҳозир айтганимиз маъқул.",
            "samples_title": "Бир йил қандай кўринади",
            "samples_lede": "Муҳаррирда яратилган намуна китоблар — ҳар бир саҳифани "
                            "ўзгартириш мумкин.",
            "captions": ["32 саҳифа · Болалар билан ўтган йил",
                         "48 саҳифа · Уйдаги Янги йил",
                         "96 саҳифа · Бутун йил, ойма-ой"],
            "band_title": "Бир йиллик суратлар — уларнинг қўлида",
        },
        "kaa": {
            "title": "Jańa jılǵa fotokitap — RS Pixel",
            "desc": "Usı jılǵı súwretlerińizdi haqıyqıy qattı muqabalı kitapqa "
                    "aylandırıń. Ápiwayı onlayn redaktorda ózińiz jaratıń — biz "
                    "basıp shıǵaramız hám Ózbekstannıń qálegen jerine jetkeremiz.",
            "kicker": "Onlayn redaktor · Basıw hám jetkeriw",
            "h1": "Sizdiń jılıńız. Sizdiń súwretlerińiz. Olardıń Jańa jıl sıylıǵı.",
            "lede": "Bir jıllıq súwretler telefonda jatır hám olardı basqa heshkim "
                    "ashpaydı. Olardan qattı muqabalı kitap jıynań: siz bir keshte "
                    "jaratasız, biz basıp shıǵaramız hám Ózbekstannıń qálegen "
                    "jerine jetkeremiz.",
            "timing_title": "{order_by}ge shekem buyırtpa beriń",
            "timing_body": "Basıw hám jetkeriw shama menen 30 kún aladı. "
                           "{order_by}ge shekem buyırtpa berseńiz, kitap "
                           "31-dekabrden ádewir burın jetip keledi. Odan keshigigende "
                           "úlgeriwimizdi wáde ete almaymız — yanvarda keshirim "
                           "soraǵannan kóre házir aytqanımız durıs.",
            "samples_title": "Bir jıl qanday kórinedi",
            "samples_lede": "Redaktorda jaratılǵan úlgi kitaplar — hár bir betti "
                            "ózgertiwge boladı.",
            "captions": ["32 bet · Balalar menen ótken jıl",
                         "48 bet · Úydegi Jańa jıl",
                         "96 bet · Pútkil jıl, aydan-ayǵa"],
            "band_title": "Bir jıllıq súwretler — olardıń qolında",
        },
    },
    "family": {
        "en": {
            "title": "A family photo book — RS Pixel",
            "desc": "Turn your family photos into a real printed hardcover. Design "
                    "it yourself in a simple online editor; we print it and deliver "
                    "anywhere in Uzbekistan.",
            "kicker": "Online editor · Printed & shipped",
            "h1": "Your family. Your photos. Your&nbsp;book.",
            "lede": "The photographs everyone loves are the ones nobody ever prints. "
                    "Put them in a hardcover book — you design it yourself in an "
                    "evening, we print it and deliver it anywhere in Uzbekistan.",
            "timing_title": "About 30 days, door to door",
            "timing_body": "Printing and delivery take about 30 days from payment. We "
                           "print your design page by page, check it, and ship it to "
                           "your address.",
            "samples_title": "Books families make",
            "samples_lede": "Sample books designed in the editor — every page is "
                            "yours to change.",
            "captions": ["16 pages · A first year",
                         "48 pages · Three generations",
                         "96 pages · A year of family"],
            "band_title": "The photos deserve better than a phone",
        },
        "ru": {
            "title": "Семейная фотокнига — RS Pixel",
            "desc": "Превратите семейные фотографии в настоящую книгу в твёрдой "
                    "обложке. Сделайте её сами в простом онлайн-редакторе — мы "
                    "напечатаем и доставим в любую точку Узбекистана.",
            "kicker": "Онлайн-редактор · Печать и доставка",
            "h1": "Ваша семья. Ваши фото. Ваша&nbsp;книга.",
            "lede": "Фотографии, которые любят все, — это те, которые никто не "
                    "печатает. Соберите из них книгу в твёрдой обложке: вы делаете "
                    "её за вечер, мы печатаем и доставляем в любую точку "
                    "Узбекистана.",
            "timing_title": "Около 30 дней от двери до двери",
            "timing_body": "Печать и доставка занимают около 30 дней с момента "
                           "оплаты. Мы печатаем ваш макет, проверяем каждую "
                           "страницу и отправляем по вашему адресу.",
            "samples_title": "Какие книги собирают семьи",
            "samples_lede": "Образцы книг, сделанных в редакторе — любую страницу "
                            "можно изменить.",
            "captions": ["16 страниц · Первый год",
                         "48 страниц · Три поколения",
                         "96 страниц · Год семьи"],
            "band_title": "Эти фотографии заслуживают большего, чем телефон",
        },
        "uz": {
            "title": "Oilaviy fotokitob — RS Pixel",
            "desc": "Oilaviy suratlaringizni haqiqiy qattiq muqovali kitobga "
                    "aylantiring. Oddiy onlayn muharrirda oʻzingiz yarating — biz "
                    "chop etamiz va Oʻzbekistonning istalgan nuqtasiga yetkazamiz.",
            "kicker": "Onlayn muharrir · Chop etish va yetkazish",
            "h1": "Sizning oilangiz. Sizning suratlaringiz. Sizning kitobingiz.",
            "lede": "Hamma yaxshi koʻradigan suratlar — aynan hech kim chop "
                    "etmaydiganlari. Ulardan qattiq muqovali kitob yigʻing: siz bir "
                    "kechada yaratasiz, biz chop etamiz va Oʻzbekistonning istalgan "
                    "nuqtasiga yetkazamiz.",
            "timing_title": "Eshikdan eshikkacha taxminan 30 kun",
            "timing_body": "Chop etish va yetkazish toʻlovdan soʻng taxminan 30 kun "
                           "oladi. Dizayningizni chop etamiz, har bir sahifani "
                           "tekshiramiz va manzilingizga joʻnatamiz.",
            "samples_title": "Oilalar qanday kitob yigʻadi",
            "samples_lede": "Muharrirda yaratilgan namuna kitoblar — har bir sahifani "
                            "oʻzgartirish mumkin.",
            "captions": ["16 sahifa · Birinchi yil",
                         "48 sahifa · Uch avlod",
                         "96 sahifa · Oila yili"],
            "band_title": "Bu suratlar telefondan koʻra koʻproqqa loyiq",
        },
        "uz-cyrl": {
            "title": "Оилавий фотокитоб — RS Pixel",
            "desc": "Оилавий суратларингизни ҳақиқий қаттиқ муқовали китобга "
                    "айлантиринг. Оддий онлайн муҳаррирда ўзингиз яратинг — биз "
                    "чоп этамиз ва Ўзбекистоннинг исталган нуқтасига етказамиз.",
            "kicker": "Онлайн муҳаррир · Чоп этиш ва етказиш",
            "h1": "Сизнинг оилангиз. Сизнинг суратларингиз. Сизнинг китобингиз.",
            "lede": "Ҳамма яхши кўрадиган суратлар — айнан ҳеч ким чоп "
                    "этмайдиганлари. Улардан қаттиқ муқовали китоб йиғинг: сиз бир "
                    "кечада яратасиз, биз чоп этамиз ва Ўзбекистоннинг исталган "
                    "нуқтасига етказамиз.",
            "timing_title": "Эшикдан эшиккача тахминан 30 кун",
            "timing_body": "Чоп этиш ва етказиш тўловдан сўнг тахминан 30 кун "
                           "олади. Дизайнингизни чоп этамиз, ҳар бир саҳифани "
                           "текширамиз ва манзилингизга жўнатамиз.",
            "samples_title": "Оилалар қандай китоб йиғади",
            "samples_lede": "Муҳаррирда яратилган намуна китоблар — ҳар бир саҳифани "
                            "ўзгартириш мумкин.",
            "captions": ["16 саҳифа · Биринчи йил",
                         "48 саҳифа · Уч авлод",
                         "96 саҳифа · Оила йили"],
            "band_title": "Бу суратлар телефондан кўра кўпроққа лойиқ",
        },
        "kaa": {
            "title": "Shańaraq fotokitabı — RS Pixel",
            "desc": "Shańaraq súwretlerińizdi haqıyqıy qattı muqabalı kitapqa "
                    "aylandırıń. Ápiwayı onlayn redaktorda ózińiz jaratıń — biz "
                    "basıp shıǵaramız hám Ózbekstannıń qálegen jerine jetkeremiz.",
            "kicker": "Onlayn redaktor · Basıw hám jetkeriw",
            "h1": "Sizdiń shańaraǵıńız. Sizdiń súwretlerińiz. Sizdiń kitabıńız.",
            "lede": "Hámme jaqsı kóretuǵın súwretler — dál heshkim basıp "
                    "shıǵarmaytuǵınları. Olardan qattı muqabalı kitap jıynań: siz bir "
                    "keshte jaratasız, biz basıp shıǵaramız hám Ózbekstannıń qálegen "
                    "jerine jetkeremiz.",
            "timing_title": "Esikten esikke shekem shama menen 30 kún",
            "timing_body": "Basıw hám jetkeriw tólemnen keyin shama menen 30 kún "
                           "aladı. Dizaynıńızdı basıp shıǵaramız, hár bir betti "
                           "tekseremiz hám mánzilińizge jiberemiz.",
            "samples_title": "Shańaraqlar qanday kitap jıynaydı",
            "samples_lede": "Redaktorda jaratılǵan úlgi kitaplar — hár bir betti "
                            "ózgertiwge boladı.",
            "captions": ["16 bet · Birinshi jıl",
                         "48 bet · Úsh áwlad",
                         "96 bet · Shańaraq jılı"],
            "band_title": "Bul súwretler telefonnan kóre kóbirekke ılayıq",
        },
    },
}

CONTACTS = [
    ('tel:+998701647664', '+998 70 164-76-64', ''),
    ('mailto:merelyriki@gmail.com', 'merelyriki@gmail.com', ''),
    ('https://t.me/Eurohand1', 'Telegram @Eurohand1', ' target="_blank" rel="noopener"'),
    ('https://www.instagram.com/rs_pixeluz/', 'Instagram @rs_pixeluz',
     ' target="_blank" rel="noopener"'),
]


def sample_card(ink: str, tint: str, badge: str, caption: str) -> str:
    """A drawn book spread. Flat fills, no gradient ids — five of these on a
    page with shared ids would each redefine the others' colours."""
    return f"""      <figure class="story-card">
        <div class="story-art"><svg viewBox="0 0 360 230" aria-hidden="true">
          <rect x="8" y="10" width="344" height="210" rx="8" fill="#ffffff" stroke="#e5e7eb"/>
          <rect x="16" y="18" width="164" height="194" fill="{ink}"/>
          <rect x="180" y="18" width="164" height="194" fill="#fbfbfc"/>
          <rect x="196" y="34" width="132" height="118" fill="{tint}"/>
          <rect x="196" y="164" width="104" height="8" rx="4" fill="#d7dbe2"/>
          <rect x="196" y="180" width="72" height="8" rx="4" fill="#e5e7eb"/>
          <rect x="178" y="18" width="4" height="194" fill="rgba(0,0,0,.08)"/>
        </svg></div>
        <figcaption><span class="badge-sample">{badge}</span> {caption}</figcaption>
      </figure>
"""


def render(lang: str, slug: str) -> str:
    c = CHROME[lang]
    o = OCCASIONS[slug][lang]
    dir_, locale, hreflang, _ = LANGS[lang]

    # An English landing page is one level below the site root; every other
    # language is two (/ru/new-year/). Everything relative hangs off this.
    root = "../" if lang == "en" else "../../"
    editor = f"{root}editor/"
    main_page = f"{root}{dir_}" or root
    url = f"{SITE}/{dir_}{slug}/"
    order_by = NEW_YEAR_ORDER_BY[lang]

    alts = "\n".join(
        f'<link rel="alternate" hreflang="{LANGS[a][2]}" '
        f'href="{SITE}/{LANGS[a][0]}{slug}/">' for a in LANGS)
    alt_locales = "\n".join(
        f'<meta property="og:locale:alternate" content="{LANGS[a][1]}">'
        for a in LANGS if a != lang)
    lang_links = "\n".join(
        f'      <a href="{root}{LANGS[a][0]}{slug}/" lang="{LANGS[a][2]}" '
        f'hreflang="{LANGS[a][2]}">{LANGS[a][3]}</a>'
        for a in LANGS if a != lang)
    header_langs = "\n".join(
        f'        <a href="{root}{LANGS[a][0]}{slug}/" lang="{LANGS[a][2]}" '
        f'hreflang="{LANGS[a][2]}">{LANGS[a][3]}</a>'
        for a in LANGS if a != lang)

    steps = "\n".join(
        f"      <li>\n        <h3>{h}</h3>\n        <p>{p}</p>\n      </li>"
        for h, p in c["steps"])
    cards = "".join(
        sample_card(ink, tint, c["samples_badge"], cap)
        for (ink, tint), cap in zip(PALETTES[slug], o["captions"], strict=True))
    contacts = "\n".join(
        f'      <a href="{href}"{attr}>{label}</a>' for href, label, attr in CONTACTS)

    return f"""<!DOCTYPE html>
<html lang="{hreflang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<!-- GENERATED by backend/scripts/build_landings.py — edit the copy there.
     tests/test_landing_pages.py fails if this file and that script differ. -->
<title>{o["title"]}</title>
<meta name="description" content="{o["desc"]}">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%232456d6'/%3E%3Cpath d='M8 9h7v14H8z' fill='%23ffffff'/%3E%3Cpath d='M17 9h7v14h-7z' fill='%23dbe4ff'/%3E%3C/svg%3E">
<link rel="stylesheet" href="{root}assets/style.css">
<script src="{root}assets/lang.js" data-page-lang="{lang}" data-root="{root}" data-page="{slug}/" data-entry="{"root" if lang == "en" else ""}"></script>
<meta property="og:type" content="website">
<meta property="og:site_name" content="RS Pixel">
<meta property="og:title" content="{o["title"]}">
<meta property="og:description" content="{o["desc"]}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE}/assets/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:type" content="image/png">
<meta property="og:image:alt" content="RS Pixel — a lay-flat photo book opened across two pages">
<meta property="og:locale" content="{locale}">
{alt_locales}
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="{url}">
{alts}
<link rel="alternate" hreflang="x-default" href="{SITE}/{slug}/">
</head>
<body>

<header class="site-header">
  <div class="wrap header-row">
    <a class="brand" href="{main_page}">
      <svg class="brand-mark" width="26" height="26" viewBox="0 0 32 32" aria-hidden="true">
        <rect width="32" height="32" rx="7" fill="#2456d6"/>
        <path d="M8 9h7v14H8z" fill="#ffffff"/>
        <path d="M17 9h7v14h-7z" fill="#dbe4ff"/>
      </svg>
      RS Pixel
    </a>
    <nav class="site-nav" aria-label="Main">
      <a href="#how">{c["how_eyebrow"]}</a>
      <a href="{main_page}">{c["full_site"]}</a>
    </nav>
    <a class="btn btn-primary btn-small header-cta" href="{editor}">{c["skip"]}</a>
    <details class="lang-menu">
      <summary aria-label="Language">{hreflang.split("-")[0].upper()}</summary>
      <div class="lang-list">
{header_langs}
      </div>
    </details>
  </div>
</header>

<main id="top">

<section class="hero">
  <div class="wrap hero-grid">
    <div>
      <span class="hero-kicker">{o["kicker"]}</span>
      <h1>{o["h1"]}</h1>
      <p class="lede">{o["lede"]}</p>
      <div class="hero-cta">
        <a class="btn btn-primary" href="{editor}">{c["skip"]}</a>
        <a class="btn btn-ghost" href="#how">{c["cta_secondary"]}</a>
      </div>
      <p class="hero-meta">{c["hero_meta"]}</p>
    </div>
    <div class="hero-art">
      <svg viewBox="0 0 720 500" role="img" aria-label="An open photo book across two pages">
        <rect x="10" y="10" width="700" height="480" rx="16" fill="#ffffff" stroke="#e4e8f0"/>
        <rect x="40" y="70" width="310" height="360" fill="{PALETTES[slug][0][0]}"/>
        <rect x="370" y="70" width="310" height="360" fill="#fbfbfc"/>
        <rect x="400" y="100" width="250" height="200" fill="{PALETTES[slug][0][1]}"/>
        <rect x="400" y="326" width="196" height="14" rx="7" fill="#d7dbe2"/>
        <rect x="400" y="356" width="140" height="14" rx="7" fill="#e5e7eb"/>
        <rect x="352" y="70" width="18" height="360" fill="rgba(0,0,0,.07)"/>
      </svg>
    </div>
  </div>
</section>

<section class="section">
  <div class="wrap">
    <div class="cta-band">
      <div>
        <h2>{o["timing_title"].format(order_by=order_by)}</h2>
        <p>{o["timing_body"].format(order_by=order_by)}</p>
      </div>
      <a class="btn btn-primary" href="{editor}">{c["skip"]}</a>
    </div>
  </div>
</section>

<section id="how" class="section alt">
  <div class="wrap">
    <div class="section-head">
      <span class="eyebrow">{c["how_eyebrow"]}</span>
      <h2>{c["how_title"]}</h2>
    </div>
    <ol class="steps">
{steps}
    </ol>
  </div>
</section>

<section class="section">
  <div class="wrap">
    <div class="section-head">
      <span class="eyebrow">{c["samples_badge"]}</span>
      <h2>{o["samples_title"]}</h2>
      <p>{o["samples_lede"]}</p>
    </div>
    <div class="story-grid">
{cards}    </div>
  </div>
</section>

<section class="section alt">
  <div class="wrap">
    <div class="cta-band">
      <div>
        <h2>{o["band_title"]}</h2>
        <p>{c["band_body"]}</p>
      </div>
      <a class="btn btn-primary" href="{editor}">{c["skip"]}</a>
    </div>
  </div>
</section>

</main>

<footer class="site-footer">
  <div class="wrap footer-grid">
    <div class="f-col f-brand">
      <strong>RS Pixel</strong>
      <p>{c["f_brand"]}</p>
      <p>{c["f_delivery"]}</p>
    </div>
    <nav class="f-col" aria-label="Product">
      <h3>{c["f_product"]}</h3>
      <a href="{main_page}">{c["f_main"]}</a>
      <a href="#how">{c["how_eyebrow"]}</a>
      <a href="{editor}" class="f-cta">{c["f_create"]}</a>
    </nav>
    <nav class="f-col" aria-label="Support">
      <h3>{c["f_support"]}</h3>
      <a href="{main_page}#faq">{c["f_faq"]}</a>
      <a href="{editor}#track">{c["f_track"]}</a>
      <a href="{main_page}#reprint">{c["f_reprint"]}</a>
    </nav>
    <nav class="f-col" aria-label="Contacts">
      <h3>{c["f_contacts"]}</h3>
{contacts}
    </nav>
    <nav class="f-col" aria-label="Language">
      <h3>{c["f_language"]}</h3>
      <span class="f-current">{LANGS[lang][3]}</span>
{lang_links}
    </nav>
  </div>
  <div class="wrap f-bottom">{c["f_bottom"]}</div>
</footer>

</body>
</html>
"""


def outputs() -> dict[str, str]:
    """{path relative to the repo root: rendered html} for every page."""
    return {f"{LANGS[lang][0]}{slug}/index.html": render(lang, slug)
            for slug in OCCASIONS for lang in LANGS}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if the committed pages differ")
    args = ap.parse_args(argv)

    stale = []
    for rel, html in outputs().items():
        path = REPO / rel
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == html:
            continue
        stale.append(rel)
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(html, encoding="utf-8")

    if args.check:
        for rel in stale:
            print(f"stale: {rel}")
        print(f"{len(stale)} page(s) differ" if stale else "all pages up to date")
        return 1 if stale else 0
    for rel in stale:
        print(f"wrote {rel}")
    print(f"{len(stale)} page(s) written, {len(outputs()) - len(stale)} unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
