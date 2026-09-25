"""Privacy policy and terms — P2-4.

Customers upload photographs of their families, and until now the site said
nothing about what happens to them. That is a trust gap on its own, and in
practice a payment acquirer will ask for both documents before approving an
account.

EVERY FACT IN HERE WAS READ OUT OF THE CODE, not drafted from a template:

  * 30 days is `books.DRAFT_RETENTION`, and it restarts on every edit
    (`books.py` sets `expires_at` again on each mutation), so the document
    says "30 days after you last open it" rather than "after you create it";
  * expiry really deletes the stored files — `lifecycle.expire_drafts`
    collects the original, display and thumbnail keys plus the preview pages
    and removes them;
  * a book that reached `locked` or `ordered` is NEVER expired, so order
    files are kept until somebody asks for them to go. The document says
    exactly that rather than inventing a period we do not implement;
  * the printer really does receive the print files, so that disclosure is
    made rather than glossed;
  * derived files carry no EXIF, which `tests/test_exif_privacy.py` proves
    against a GPS-tagged fixture rather than asserting in a comment.

A privacy policy is the one page on a site where a sentence that is not
true is worse than a sentence that is missing.

Regenerate:  cd backend && .venv/bin/python scripts/build_policies.py
"""
import argparse
import pathlib
import sys

# Runnable as `python scripts/build_policies.py` from backend/, the way the
# other scripts here are, without needing PYTHONPATH set first.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from scripts.build_landings import CONTACTS, LANGS, REPO, SITE  # noqa: E402

SLUGS = ("privacy", "terms")

# Labels shared by both documents.
CHROME = {
    "en": {
        "back": "The full site", "create": "Create your book",
        "f_contacts": "Contacts", "f_language": "Language",
        "updated": "Last updated 25 September 2026",
        "bottom": "© RS Pixel · Made in Uzbekistan",
        "other": {"privacy": "Terms of service", "terms": "Privacy policy"},
    },
    "ru": {
        "back": "Основной сайт", "create": "Создать книгу",
        "f_contacts": "Контакты", "f_language": "Язык",
        "updated": "Обновлено 25 сентября 2026",
        "bottom": "© RS Pixel · Сделано в Узбекистане",
        "other": {"privacy": "Условия использования", "terms": "Политика конфиденциальности"},
    },
    "uz": {
        "back": "Asosiy sayt", "create": "Kitob yaratish",
        "f_contacts": "Aloqa", "f_language": "Til",
        "updated": "2026-yil 25-sentyabrda yangilangan",
        "bottom": "© RS Pixel · Oʻzbekistonda yaratilgan",
        "other": {"privacy": "Foydalanish shartlari", "terms": "Maxfiylik siyosati"},
    },
    "uz-cyrl": {
        "back": "Асосий сайт", "create": "Китоб яратиш",
        "f_contacts": "Алоқа", "f_language": "Тил",
        "updated": "2026-йил 25-сентябрда янгиланган",
        "bottom": "© RS Pixel · Ўзбекистонда яратилган",
        "other": {"privacy": "Фойдаланиш шартлари", "terms": "Махфийлик сиёсати"},
    },
    "kaa": {
        "back": "Tiykarǵı sayt", "create": "Kitap jaratıw",
        "f_contacts": "Baylanıs", "f_language": "Til",
        "updated": "2026-jıl 25-sentyabrde jańalandı",
        "bottom": "© RS Pixel · Ózbekstanda jaratılǵan",
        "other": {"privacy": "Paydalanıw shártleri", "terms": "Qupıyalıq siyasatı"},
    },
}

# Each document is (title, description, intro, [(heading, [paragraphs])]).
DOCS = {
    "privacy": {
        "en": (
            "Privacy policy — RS Pixel",
            "What RS Pixel stores when you make a photo book, how long we keep "
            "it, and how to have it deleted.",
            "You upload photographs of your family to make a book. This page "
            "says plainly what we do with them. If anything here is unclear, "
            "write to us — the addresses are at the bottom.",
            [
                ("What we store", [
                    "The photographs you upload, the layout you design, and "
                    "smaller copies of each photo that the editor and the "
                    "preview use.",
                    "When you place an order: your name, phone number, "
                    "delivery address, and an email address if you gave one. "
                    "If you pay by card transfer, the receipt image you send "
                    "us.",
                    "We do not ask for anything else, and there is no account "
                    "to create.",
                ]),
                ("We remove the location from every copy we make", [
                    "A phone usually writes the exact coordinates of where a "
                    "photo was taken into the file — often your home. Every "
                    "copy we generate from your photo, including the file the "
                    "printer receives, is re-encoded with all of that metadata "
                    "removed. Only the original you uploaded still has it, and "
                    "the original is never sent anywhere.",
                ]),
                ("How long we keep it", [
                    "An unfinished book is deleted 30 days after the last time "
                    "you opened it, and its photographs are deleted from our "
                    "storage with it. Every edit starts the 30 days again, so "
                    "a book you are still working on does not disappear.",
                    "Once you order, we keep the book and its photographs so "
                    "we can print it, reprint it if something goes wrong, and "
                    "answer you if you ask about the order later. We do not "
                    "delete those automatically — ask us and we will.",
                ]),
                ("Who else sees your photographs", [
                    "The print shop, and only the finished print files for an "
                    "order you placed. Nobody else.",
                    "We never sell your photographs, never share them with "
                    "anyone else, and never use them in advertising, on this "
                    "site, or anywhere public unless you have told us in "
                    "writing that we may.",
                ]),
                ("How to have it deleted", [
                    "Write to us from the phone number or email you ordered "
                    "with, or message us on Telegram, and say what you want "
                    "removed. If it is an order, include the order reference. "
                    "We delete it and confirm when it is done.",
                    "You can also delete individual photographs yourself in "
                    "the editor at any time before you order.",
                ]),
                ("Cookies, and how we count visits", [
                    "Two small first-party cookies. One is a random id that "
                    "strings your own steps together — opened the editor, "
                    "uploaded a photo, placed an order — so we can see where "
                    "people give up. The other remembers which advert or link "
                    "brought you here, so we know which ones are worth paying "
                    "for.",
                    "Neither holds your name, phone or email, neither can be "
                    "read by the page itself, and we use no third-party "
                    "analytics or advertising trackers at all. Delete them in "
                    "your browser whenever you like — nothing on the site "
                    "stops working.",
                ]),
                ("Who to contact", [
                    "RS Pixel, Tashkent, Uzbekistan. Phone and Telegram "
                    "+998 70 164-76-64, email merelyriki@gmail.com. A real "
                    "person reads these.",
                ]),
            ],
        ),
        "ru": (
            "Политика конфиденциальности — RS Pixel",
            "Что RS Pixel хранит, когда вы делаете фотокнигу, как долго и как "
            "запросить удаление.",
            "Вы загружаете фотографии своей семьи, чтобы сделать книгу. Здесь "
            "прямо написано, что мы с ними делаем. Если что-то непонятно — "
            "напишите нам, контакты внизу.",
            [
                ("Что мы храним", [
                    "Загруженные вами фотографии, сделанный вами макет и "
                    "уменьшенные копии каждой фотографии — их использует "
                    "редактор и предпросмотр.",
                    "При заказе: имя, номер телефона, адрес доставки и почту, "
                    "если вы её указали. Если вы платите переводом на карту — "
                    "присланный вами чек.",
                    "Больше мы ничего не спрашиваем, и аккаунт создавать не "
                    "нужно.",
                ]),
                ("Мы убираем геометку из каждой копии", [
                    "Телефон обычно записывает в файл точные координаты места "
                    "съёмки — часто это ваш дом. Каждая копия, которую мы "
                    "создаём из вашей фотографии, включая файл для типографии, "
                    "пересохраняется без этих данных. Координаты остаются "
                    "только в исходном файле, а исходный файл мы никуда не "
                    "отправляем.",
                ]),
                ("Сколько мы это храним", [
                    "Незаконченная книга удаляется через 30 дней после того, "
                    "как вы открывали её в последний раз, вместе с "
                    "фотографиями из нашего хранилища. Каждое изменение "
                    "отсчитывает 30 дней заново, так что книга, над которой вы "
                    "работаете, не пропадёт.",
                    "После заказа мы храним книгу и фотографии, чтобы "
                    "напечатать её, перепечатать при браке и ответить вам, "
                    "если вы спросите о заказе позже. Автоматически мы их не "
                    "удаляем — попросите, и мы удалим.",
                ]),
                ("Кто ещё видит ваши фотографии", [
                    "Типография — и только готовые файлы печати по "
                    "оформленному вами заказу. Больше никто.",
                    "Мы не продаём ваши фотографии, не передаём их третьим "
                    "лицам и не используем в рекламе, на этом сайте или "
                    "где-либо публично, если вы письменно не разрешили.",
                ]),
                ("Как запросить удаление", [
                    "Напишите нам с того номера или почты, с которых "
                    "оформляли заказ, или в Telegram, и скажите, что нужно "
                    "удалить. Если это заказ — укажите его номер. Мы удалим и "
                    "подтвердим.",
                    "Отдельные фотографии вы можете удалить сами в редакторе в "
                    "любой момент до заказа.",
                ]),
                ("Куки и как мы считаем визиты", [
                    "Два небольших собственных куки-файла. Один — случайный "
                    "идентификатор, который связывает ваши шаги: открыли "
                    "редактор, загрузили фото, оформили заказ, — чтобы мы "
                    "видели, где люди бросают. Второй запоминает, какая "
                    "реклама или ссылка привела вас сюда, чтобы понимать, за "
                    "что имеет смысл платить.",
                    "Ни в одном нет вашего имени, телефона или почты, ни один "
                    "не читается самой страницей, и мы вообще не используем "
                    "сторонние системы аналитики и рекламные трекеры. Удалите "
                    "их в браузере в любой момент — сайт продолжит работать.",
                ]),
                ("Контакты", [
                    "RS Pixel, Ташкент, Узбекистан. Телефон и Telegram "
                    "+998 70 164-76-64, почта merelyriki@gmail.com. Это читает "
                    "живой человек.",
                ]),
            ],
        ),
        "uz": (
            "Maxfiylik siyosati — RS Pixel",
            "Fotokitob yaratganingizda RS Pixel nimani saqlaydi, qancha "
            "muddat va oʻchirishni qanday soʻrash mumkin.",
            "Siz kitob yaratish uchun oilangiz suratlarini yuklaysiz. Bu "
            "sahifada ular bilan nima qilishimiz ochiq yozilgan. Biror narsa "
            "tushunarsiz boʻlsa — bizga yozing, aloqa pastda.",
            [
                ("Biz nimani saqlaymiz", [
                    "Siz yuklagan suratlar, siz yaratgan maket va har bir "
                    "suratning kichik nusxalari — ularni muharrir va "
                    "koʻrib chiqish ishlatadi.",
                    "Buyurtma berganda: ism, telefon raqami, yetkazib berish "
                    "manzili va agar kiritgan boʻlsangiz, pochta. Karta orqali "
                    "toʻlasangiz — yuborgan chekingiz.",
                    "Boshqa hech narsa soʻramaymiz va akkaunt ochish shart "
                    "emas.",
                ]),
                ("Har bir nusxadan joylashuvni olib tashlaymiz", [
                    "Telefon odatda suratga olingan joyning aniq "
                    "koordinatalarini faylga yozadi — koʻpincha bu sizning "
                    "uyingiz. Suratingizdan yaratadigan har bir nusxa, shu "
                    "jumladan bosmaxonaga ketadigan fayl ham, bu maʼlumotsiz "
                    "qayta saqlanadi. Koordinatalar faqat asl faylda qoladi, "
                    "asl faylni esa biz hech qayerga yubormaymiz.",
                ]),
                ("Qancha muddat saqlaymiz", [
                    "Tugallanmagan kitob siz uni oxirgi marta ochganingizdan "
                    "30 kun keyin, suratlari bilan birga oʻchiriladi. Har bir "
                    "oʻzgartirish 30 kunni qaytadan boshlaydi, shuning uchun "
                    "ustida ishlayotgan kitobingiz yoʻqolmaydi.",
                    "Buyurtmadan keyin kitob va suratlarni saqlaymiz: chop "
                    "etish, nuqson boʻlsa qayta chop etish va keyinroq "
                    "soʻrasangiz javob berish uchun. Ularni avtomatik "
                    "oʻchirmaymiz — ayting, oʻchiramiz.",
                ]),
                ("Suratlaringizni yana kim koʻradi", [
                    "Bosmaxona — va faqat siz bergan buyurtmaning tayyor chop "
                    "fayllari. Boshqa hech kim.",
                    "Biz suratlaringizni sotmaymiz, birovga bermaymiz va "
                    "yozma ruxsatingizsiz reklamada, bu saytda yoki ochiq "
                    "joyda ishlatmaymiz.",
                ]),
                ("Oʻchirishni qanday soʻrash mumkin", [
                    "Buyurtma bergan raqamingiz yoki pochtangizdan yozing "
                    "yoki Telegramga yozing va nimani oʻchirish kerakligini "
                    "ayting. Bu buyurtma boʻlsa — raqamini qoʻshing. "
                    "Oʻchiramiz va tasdiqlaymiz.",
                    "Ayrim suratlarni buyurtmagacha istalgan vaqtda muharrirda "
                    "oʻzingiz oʻchirishingiz mumkin.",
                ]),
                ("Kuki fayllar va tashriflarni qanday sanaymiz", [
                    "Ikkita kichik oʻz kuki faylimiz. Biri — tasodifiy "
                    "identifikator: muharrirni ochdingiz, surat yukladingiz, "
                    "buyurtma berdingiz — qadamlaringizni bogʻlaydi, shunda "
                    "odamlar qayerda toʻxtashini koʻramiz. Ikkinchisi qaysi "
                    "reklama yoki havola sizni bu yerga olib kelganini eslab "
                    "qoladi.",
                    "Ularda ismingiz, telefoningiz yoki pochtangiz yoʻq, "
                    "ularni sahifaning oʻzi oʻqiy olmaydi va biz uchinchi "
                    "tomon analitikasi hamda reklama kuzatuvchilaridan "
                    "umuman foydalanmaymiz. Istalgan vaqtda brauzerda "
                    "oʻchiring — sayt ishlashda davom etadi.",
                ]),
                ("Kim bilan bogʻlanish", [
                    "RS Pixel, Toshkent, Oʻzbekiston. Telefon va Telegram "
                    "+998 70 164-76-64, pochta merelyriki@gmail.com. Buni "
                    "tirik odam oʻqiydi.",
                ]),
            ],
        ),
        "uz-cyrl": (
            "Махфийлик сиёсати — RS Pixel",
            "Фотокитоб яратганингизда RS Pixel нимани сақлайди, қанча муддат "
            "ва ўчиришни қандай сўраш мумкин.",
            "Сиз китоб яратиш учун оилангиз суратларини юклайсиз. Бу саҳифада "
            "улар билан нима қилишимиз очиқ ёзилган. Бирор нарса тушунарсиз "
            "бўлса — бизга ёзинг, алоқа пастда.",
            [
                ("Биз нимани сақлаймиз", [
                    "Сиз юклаган суратлар, сиз яратган макет ва ҳар бир "
                    "суратнинг кичик нусхалари — уларни муҳаррир ва кўриб "
                    "чиқиш ишлатади.",
                    "Буюртма берганда: исм, телефон рақами, етказиб бериш "
                    "манзили ва агар киритган бўлсангиз, почта. Карта орқали "
                    "тўласангиз — юборган чекингиз.",
                    "Бошқа ҳеч нарса сўрамаймиз ва аккаунт очиш шарт эмас.",
                ]),
                ("Ҳар бир нусхадан жойлашувни олиб ташлаймиз", [
                    "Телефон одатда суратга олинган жойнинг аниқ "
                    "координаталарини файлга ёзади — кўпинча бу сизнинг "
                    "уйингиз. Суратингиздан яратадиган ҳар бир нусха, шу "
                    "жумладан босмахонага кетадиган файл ҳам, бу маълумотсиз "
                    "қайта сақланади. Координаталар фақат асл файлда қолади, "
                    "асл файлни эса биз ҳеч қаерга юбормаймиз.",
                ]),
                ("Қанча муддат сақлаймиз", [
                    "Тугалланмаган китоб сиз уни охирги марта "
                    "очганингиздан 30 кун кейин, суратлари билан бирга "
                    "ўчирилади. Ҳар бир ўзгартириш 30 кунни қайтадан "
                    "бошлайди, шунинг учун устида ишлаётган китобингиз "
                    "йўқолмайди.",
                    "Буюртмадан кейин китоб ва суратларни сақлаймиз: чоп "
                    "этиш, нуқсон бўлса қайта чоп этиш ва кейинроқ "
                    "сўрасангиз жавоб бериш учун. Уларни автоматик "
                    "ўчирмаймиз — айтинг, ўчирамиз.",
                ]),
                ("Суратларингизни яна ким кўради", [
                    "Босмахона — ва фақат сиз берган буюртманинг тайёр чоп "
                    "файллари. Бошқа ҳеч ким.",
                    "Биз суратларингизни сотмаймиз, бировга бермаймиз ва "
                    "ёзма рухсатингизсиз рекламада, бу сайтда ёки очиқ "
                    "жойда ишлатмаймиз.",
                ]),
                ("Ўчиришни қандай сўраш мумкин", [
                    "Буюртма берган рақамингиз ёки почтангиздан ёзинг ёки "
                    "Telegramга ёзинг ва нимани ўчириш кераклигини айтинг. "
                    "Бу буюртма бўлса — рақамини қўшинг. Ўчирамиз ва "
                    "тасдиқлаймиз.",
                    "Айрим суратларни буюртмагача исталган вақтда муҳаррирда "
                    "ўзингиз ўчиришингиз мумкин.",
                ]),
                ("Куки файллар ва ташрифларни қандай санаймиз", [
                    "Иккита кичик ўз куки файлимиз. Бири — тасодифий "
                    "идентификатор: муҳаррирни очдингиз, сурат юкладингиз, "
                    "буюртма бердингиз — қадамларингизни боғлайди, шунда "
                    "одамлар қаерда тўхташини кўрамиз. Иккинчиси қайси "
                    "реклама ёки ҳавола сизни бу ерга олиб келганини эслаб "
                    "қолади.",
                    "Уларда исмингиз, телефонингиз ёки почтангиз йўқ, уларни "
                    "саҳифанинг ўзи ўқий олмайди ва биз учинчи томон "
                    "аналитикаси ҳамда реклама кузатувчиларидан умуман "
                    "фойдаланмаймиз. Исталган вақтда браузерда ўчиринг — сайт "
                    "ишлашда давом этади.",
                ]),
                ("Ким билан боғланиш", [
                    "RS Pixel, Тошкент, Ўзбекистон. Телефон ва Telegram "
                    "+998 70 164-76-64, почта merelyriki@gmail.com. Буни "
                    "тирик одам ўқийди.",
                ]),
            ],
        ),
        "kaa": (
            "Qupıyalıq siyasatı — RS Pixel",
            "Fotokitap jaratqanıńızda RS Pixel nelerdi saqlaydı, qansha "
            "múddet hám óshiriwdi qalay soraw kerek.",
            "Siz kitap jaratıw ushın shańaraǵıńızdıń súwretlerin júkleysiz. "
            "Bul bette olar menen ne isleytuǵınımız ashıq jazılǵan. Bir nárse "
            "túsiniksiz bolsa — bizge jazıń, baylanıs tómende.",
            [
                ("Biz nelerdi saqlaymız", [
                    "Siz júklegen súwretler, siz jasaǵan maket hám hár bir "
                    "súwrettiń kishi nusqaları — olardı redaktor hám kórip "
                    "shıǵıw isletedi.",
                    "Buyırtpa bergende: atıńız, telefon nomerińiz, jetkeriw "
                    "mánzili hám kirgizgen bolsańız, pochta. Karta arqalı "
                    "tóleseńiz — jibergen chegińiz.",
                    "Basqa hesh nárse soramaymız hám akkaunt ashıw shárt emes.",
                ]),
                ("Hár bir nusqadan jaylasıwdı alıp taslaymız", [
                    "Telefon ádette súwretke alınǵan jerdiń anıq "
                    "koordinatalarin faylǵa jazadı — kóbinese bul sizdiń "
                    "úyińiz. Súwretińizden jaratatuǵın hár bir nusqa, sonıń "
                    "ishinde baspaxanaǵa ketetuǵın fayl da, bul maǵlıwmatsız "
                    "qayta saqlanadı. Koordinatalar tek deslepki faylda "
                    "qaladı, deslepki fayldı bolsa biz hesh qayerge "
                    "jibermeymiz.",
                ]),
                ("Qansha múddet saqlaymız", [
                    "Tamamlanbaǵan kitap siz onı aqırǵı ret ashqanıńızdan 30 "
                    "kún keyin, súwretleri menen birge óshiriledi. Hár bir "
                    "ózgeris 30 kúndi qaytadan baslaydı, sonlıqtan ústinde "
                    "islep atırǵan kitabıńız joǵalmaydı.",
                    "Buyırtpadan keyin kitap hám súwretlerdi saqlaymız: basıp "
                    "shıǵarıw, kemshilik bolsa qayta basıw hám keyinirek "
                    "sorasańız juwap beriw ushın. Olardı avtomat túrde "
                    "óshirmeymiz — aytıń, óshiremiz.",
                ]),
                ("Súwretlerińizdi taǵı kim kóredi", [
                    "Baspaxana — hám tek siz bergen buyırtpanıń tayar basıw "
                    "faylları. Basqa hesh kim.",
                    "Biz súwretlerińizdi satpaymız, basqaǵa bermeymiz hám "
                    "jazba ruqsatıńızsız reklamada, bul saytta yamasa ashıq "
                    "jerde isletpeymiz.",
                ]),
                ("Óshiriwdi qalay soraw kerek", [
                    "Buyırtpa bergen nomerińizden yamasa pochtańızdan jazıń "
                    "yamasa Telegramǵa jazıń hám nelerdi óshiriw kerekligin "
                    "aytıń. Bul buyırtpa bolsa — nomerin qosıń. Óshiremiz hám "
                    "tastıyıqlaymız.",
                    "Ayırım súwretlerdi buyırtpaǵa shekem qálegen waqıtta "
                    "redaktorda ózińiz óshire alasız.",
                ]),
                ("Kuki fayllar hám tashriflerdi qalay sanaymız", [
                    "Eki kishkene óz kuki faylımız. Biri — tosınnan shıqqan "
                    "identifikator: redaktordı ashtıńız, súwret júkledińiz, "
                    "buyırtpa berdińiz — qádemlerińizdi baylanıstıradı, sonda "
                    "adamlar qayerde toqtaytuǵının kóremiz. Ekinshisi qaysı "
                    "reklama yamasa siltem sizdi bul jerge alıp kelgenin eske "
                    "saqlaydı.",
                    "Olarda atıńız, telefonıńız yamasa pochtańız joq, olardı "
                    "bettiń ózi oqıy almaydı hám biz úshinshi tárep "
                    "analitikasınan hám reklama gúzetiwshilerinen ulıwma "
                    "paydalanbaymız. Qálegen waqıtta brauzerde óshiriń — sayt "
                    "islewin dawam etedi.",
                ]),
                ("Kim menen baylanısıw", [
                    "RS Pixel, Tashkent, Ózbekstan. Telefon hám Telegram "
                    "+998 70 164-76-64, pochta merelyriki@gmail.com. Bunı tiri "
                    "adam oqıydı.",
                ]),
            ],
        ),
    },
    "terms": {
        "en": (
            "Terms of service — RS Pixel",
            "What you are buying from RS Pixel, what it costs, when it "
            "arrives, and what happens if something is wrong.",
            "Short version: you design a book, we print it and send it to "
            "you. These are the details.",
            [
                ("What you are buying", [
                    "A printed lay-flat hardcover photo book, laid out by you "
                    "in our editor. We print the design exactly as you made "
                    "it — the same pages, the same order, the same text.",
                    "Designing is free. You pay only when you order the "
                    "printed book.",
                ]),
                ("Your photographs stay yours", [
                    "You keep every right to the photographs you upload. We "
                    "use them for one thing: making and printing your book. "
                    "See the privacy policy for what we store and for how "
                    "long.",
                    "By uploading, you confirm you are allowed to use those "
                    "photographs.",
                ]),
                ("Price, payment and delivery", [
                    "Prices are shown in Uzbek soʻm before you order and do "
                    "not change after you have paid. Payment is a card "
                    "transfer; we show the card number and the exact amount "
                    "after you place the order.",
                    "We deliver anywhere in Uzbekistan. Printing and delivery "
                    "take about 30 days from payment.",
                ]),
                ("If something is wrong with the book", [
                    "If the book arrives damaged or misprinted, tell us within "
                    "14 days of delivery and send photographs of the problem. "
                    "We reprint it free, including delivery. What that covers "
                    "is set out on the reprint policy.",
                    "Because every book is printed to your own design, we "
                    "cannot resell a returned book, so we do not take returns "
                    "for a change of mind.",
                ]),
                ("What we will not print", [
                    "We will not print material that is illegal in "
                    "Uzbekistan, or images of other people published without "
                    "their agreement. If we refuse an order on these grounds "
                    "we refund it in full.",
                ]),
                ("Who to contact", [
                    "RS Pixel, Tashkent, Uzbekistan. Phone and Telegram "
                    "+998 70 164-76-64, email merelyriki@gmail.com.",
                ]),
            ],
        ),
        "ru": (
            "Условия использования — RS Pixel",
            "Что вы покупаете у RS Pixel, сколько это стоит, когда приедет и "
            "что будет, если что-то не так.",
            "Коротко: вы делаете книгу, мы печатаем её и отправляем вам. "
            "Дальше подробности.",
            [
                ("Что вы покупаете", [
                    "Печатную фотокнигу в твёрдой обложке, раскрывающуюся "
                    "плоско, с макетом, который вы сделали в нашем редакторе. "
                    "Мы печатаем макет ровно таким, каким вы его сделали — те "
                    "же страницы, тот же порядок, тот же текст.",
                    "Создание бесплатно. Вы платите только при заказе печати.",
                ]),
                ("Ваши фотографии остаются вашими", [
                    "Все права на загруженные фотографии остаются у вас. Мы "
                    "используем их только для одного: сделать и напечатать "
                    "вашу книгу. Что именно мы храним и сколько — в политике "
                    "конфиденциальности.",
                    "Загружая фотографии, вы подтверждаете, что имеете право "
                    "их использовать.",
                ]),
                ("Цена, оплата и доставка", [
                    "Цены показаны в сумах до заказа и не меняются после "
                    "оплаты. Оплата — переводом на карту; номер карты и точную "
                    "сумму мы показываем после оформления заказа.",
                    "Доставляем в любую точку Узбекистана. Печать и доставка "
                    "занимают около 30 дней с момента оплаты.",
                ]),
                ("Если с книгой что-то не так", [
                    "Если книга приехала повреждённой или с браком печати — "
                    "сообщите в течение 14 дней после доставки и пришлите "
                    "фотографии проблемы. Перепечатаем бесплатно, вместе с "
                    "доставкой. Что входит — в правилах перепечатки.",
                    "Каждая книга печатается по вашему личному макету и не "
                    "может быть продана другому, поэтому возврат из-за "
                    "передумали мы не делаем.",
                ]),
                ("Что мы не будем печатать", [
                    "Мы не печатаем материалы, запрещённые законодательством "
                    "Узбекистана, и изображения других людей, опубликованные "
                    "без их согласия. Если мы отказываем по этим причинам — "
                    "возвращаем оплату полностью.",
                ]),
                ("Контакты", [
                    "RS Pixel, Ташкент, Узбекистан. Телефон и Telegram "
                    "+998 70 164-76-64, почта merelyriki@gmail.com.",
                ]),
            ],
        ),
        "uz": (
            "Foydalanish shartlari — RS Pixel",
            "RS Pixeldan nima sotib olayotganingiz, narxi, qachon yetib "
            "kelishi va biror narsa notoʻgʻri boʻlsa nima boʻlishi.",
            "Qisqacha: siz kitob yaratasiz, biz chop etamiz va sizga "
            "joʻnatamiz. Quyida tafsilotlar.",
            [
                ("Nima sotib olayotganingiz", [
                    "Siz muharrirda yaratgan maket boʻyicha chop etilgan, "
                    "tekis ochiladigan qattiq muqovali fotokitob. Maketni siz "
                    "yaratgan holda chop etamiz — oʻsha sahifalar, oʻsha "
                    "tartib, oʻsha matn.",
                    "Yaratish bepul. Faqat chop etishga buyurtma berganingizda "
                    "toʻlaysiz.",
                ]),
                ("Suratlaringiz sizniki boʻlib qoladi", [
                    "Yuklangan suratlarga boʻlgan barcha huquqlar sizda "
                    "qoladi. Biz ulardan faqat bitta narsa uchun "
                    "foydalanamiz: kitobingizni yaratish va chop etish. Nimani "
                    "va qancha saqlashimiz maxfiylik siyosatida.",
                    "Surat yuklash bilan siz ulardan foydalanish huquqingiz "
                    "borligini tasdiqlaysiz.",
                ]),
                ("Narx, toʻlov va yetkazish", [
                    "Narxlar buyurtmadan oldin soʻmda koʻrsatiladi va "
                    "toʻlovdan keyin oʻzgarmaydi. Toʻlov — karta oʻtkazmasi; "
                    "karta raqami va aniq summani buyurtmadan keyin "
                    "koʻrsatamiz.",
                    "Oʻzbekistonning istalgan nuqtasiga yetkazib beramiz. Chop "
                    "etish va yetkazish toʻlovdan soʻng taxminan 30 kun oladi.",
                ]),
                ("Kitobda nuqson boʻlsa", [
                    "Kitob shikastlangan yoki nuqson bilan yetib kelsa — "
                    "yetkazilgandan keyin 14 kun ichida ayting va muammoning "
                    "suratlarini yuboring. Bepul qayta chop etamiz, yetkazish "
                    "bilan birga. Nima kirishi qayta chop etish qoidalarida.",
                    "Har bir kitob sizning shaxsiy maketingiz boʻyicha chop "
                    "etiladi va boshqaga sotilmaydi, shuning uchun fikr "
                    "oʻzgargani uchun qaytarib olmaymiz.",
                ]),
                ("Nimani chop etmaymiz", [
                    "Oʻzbekiston qonunchiligida taqiqlangan materiallarni va "
                    "boshqa odamlarning roziligisiz eʼlon qilingan "
                    "tasvirlarini chop etmaymiz. Shu sababdan rad etsak — "
                    "toʻlovni toʻliq qaytaramiz.",
                ]),
                ("Kim bilan bogʻlanish", [
                    "RS Pixel, Toshkent, Oʻzbekiston. Telefon va Telegram "
                    "+998 70 164-76-64, pochta merelyriki@gmail.com.",
                ]),
            ],
        ),
        "uz-cyrl": (
            "Фойдаланиш шартлари — RS Pixel",
            "RS Pixelдан нима сотиб олаётганингиз, нархи, қачон етиб келиши "
            "ва бирор нарса нотўғри бўлса нима бўлиши.",
            "Қисқача: сиз китоб яратасиз, биз чоп этамиз ва сизга жўнатамиз. "
            "Қуйида тафсилотлар.",
            [
                ("Нима сотиб олаётганингиз", [
                    "Сиз муҳаррирда яратган макет бўйича чоп этилган, текис "
                    "очиладиган қаттиқ муқовали фотокитоб. Макетни сиз яратган "
                    "ҳолда чоп этамиз — ўша саҳифалар, ўша тартиб, ўша матн.",
                    "Яратиш бепул. Фақат чоп этишга буюртма берганингизда "
                    "тўлайсиз.",
                ]),
                ("Суратларингиз сизники бўлиб қолади", [
                    "Юкланган суратларга бўлган барча ҳуқуқлар сизда қолади. "
                    "Биз улардан фақат битта нарса учун фойдаланамиз: "
                    "китобингизни яратиш ва чоп этиш. Нимани ва қанча "
                    "сақлашимиз махфийлик сиёсатида.",
                    "Сурат юклаш билан сиз улардан фойдаланиш ҳуқуқингиз "
                    "борлигини тасдиқлайсиз.",
                ]),
                ("Нарх, тўлов ва етказиш", [
                    "Нархлар буюртмадан олдин сўмда кўрсатилади ва тўловдан "
                    "кейин ўзгармайди. Тўлов — карта ўтказмаси; карта рақами "
                    "ва аниқ суммани буюртмадан кейин кўрсатамиз.",
                    "Ўзбекистоннинг исталган нуқтасига етказиб берамиз. Чоп "
                    "этиш ва етказиш тўловдан сўнг тахминан 30 кун олади.",
                ]),
                ("Китобда нуқсон бўлса", [
                    "Китоб шикастланган ёки нуқсон билан етиб келса — "
                    "етказилгандан кейин 14 кун ичида айтинг ва муаммонинг "
                    "суратларини юборинг. Бепул қайта чоп этамиз, етказиш "
                    "билан бирга. Нима кириши қайта чоп этиш қоидаларида.",
                    "Ҳар бир китоб сизнинг шахсий макетингиз бўйича чоп "
                    "этилади ва бошқага сотилмайди, шунинг учун фикр ўзгаргани "
                    "учун қайтариб олмаймиз.",
                ]),
                ("Нимани чоп этмаймиз", [
                    "Ўзбекистон қонунчилигида тақиқланган материалларни ва "
                    "бошқа одамларнинг розилигисиз эълон қилинган тасвирларини "
                    "чоп этмаймиз. Шу сабабдан рад этсак — тўловни тўлиқ "
                    "қайтарамиз.",
                ]),
                ("Ким билан боғланиш", [
                    "RS Pixel, Тошкент, Ўзбекистон. Телефон ва Telegram "
                    "+998 70 164-76-64, почта merelyriki@gmail.com.",
                ]),
            ],
        ),
        "kaa": (
            "Paydalanıw shártleri — RS Pixel",
            "RS Pixelden ne satıp atırǵanıńız, qansha turatuǵını, qashan jetip "
            "keletuǵını hám bir nárse durıs bolmasa ne bolatuǵını.",
            "Qısqasha: siz kitap jaratasız, biz basıp shıǵaramız hám sizge "
            "jiberemiz. Tómende tolıǵıraq.",
            [
                ("Ne satıp atırǵanıńız", [
                    "Siz redaktorda jasaǵan maket boyınsha basılǵan, tegis "
                    "ashılatuǵın qattı muqabalı fotokitap. Maketti siz jasaǵan "
                    "túrde basamız — sol betler, sol tártip, sol tekst.",
                    "Jaratıw biypul. Tek basıwǵa buyırtpa bergende tóleysiz.",
                ]),
                ("Súwretlerińiz ózińizdiki bolıp qaladı", [
                    "Júklengen súwretlerge bolǵan barlıq huqıqlar sizde "
                    "qaladı. Biz olardı tek bir nárse ushın isletemiz: "
                    "kitabıńızdı jaratıw hám basıp shıǵarıw. Nelerdi hám "
                    "qansha saqlaytuǵınımız qupıyalıq siyasatında.",
                    "Súwret júklew menen siz olardan paydalanıw huqıqıńız bar "
                    "ekenin tastıyıqlaysız.",
                ]),
                ("Baha, tólem hám jetkeriw", [
                    "Bahalar buyırtpadan aldın sumda kórsetiledi hám tólemnen "
                    "keyin ózgermeydi. Tólem — karta awdarması; karta nomerin "
                    "hám anıq summanı buyırtpadan keyin kórsetemiz.",
                    "Ózbekstannıń qálegen jerine jetkerip beremiz. Basıw hám "
                    "jetkeriw tólemnen keyin shama menen 30 kún aladı.",
                ]),
                ("Kitapta kemshilik bolsa", [
                    "Kitap zaqımlanıp yamasa kemshilik penen kelse — "
                    "jetkerilgennen keyin 14 kún ishinde aytıń hám máseleniń "
                    "súwretlerin jiberiń. Biypul qayta basıp beremiz, jetkeriw "
                    "menen birge. Ne kiretuǵını qayta basıw qaǵıydalarında.",
                    "Hár bir kitap sizdiń jeke maketińiz boyınsha basıladı hám "
                    "basqaǵa satılmaydı, sonlıqtan pikir ózgergeni ushın "
                    "qaytarıp almaymız.",
                ]),
                ("Nelerdi basıp shıǵarmaymız", [
                    "Ózbekstan nızamshılıǵında qadaǵan etilgen materiallardı "
                    "hám basqa adamlardıń kelisimisiz járiyalanǵan "
                    "súwretlerin basıp shıǵarmaymız. Sol sebepten bas tartsaq "
                    "— tólemdi tolıq qaytaramız.",
                ]),
                ("Kim menen baylanısıw", [
                    "RS Pixel, Tashkent, Ózbekstan. Telefon hám Telegram "
                    "+998 70 164-76-64, pochta merelyriki@gmail.com.",
                ]),
            ],
        ),
    },
}


def render(lang: str, slug: str) -> str:
    dir_, locale, hreflang, native = LANGS[lang]
    c = CHROME[lang]
    title, desc, intro, sections = DOCS[slug][lang]
    root = "../" if lang == "en" else "../../"
    url = f"{SITE}/{dir_}{slug}/"
    other = "terms" if slug == "privacy" else "privacy"

    alts = "\n".join(
        f'<link rel="alternate" hreflang="{LANGS[a][2]}" '
        f'href="{SITE}/{LANGS[a][0]}{slug}/">' for a in LANGS)
    lang_links = "\n".join(
        f'      <a href="{root}{LANGS[a][0]}{slug}/" lang="{LANGS[a][2]}" '
        f'hreflang="{LANGS[a][2]}">{LANGS[a][3]}</a>'
        for a in LANGS if a != lang)
    contacts = "\n".join(
        f'      <a href="{href}"{attr}>{label}</a>' for href, label, attr in CONTACTS)
    body = "\n".join(
        f"      <h2>{h}</h2>\n"
        + "\n".join(f"      <p>{p}</p>" for p in paras)
        for h, paras in sections)

    return f"""<!DOCTYPE html>
<html lang="{hreflang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<!-- GENERATED by backend/scripts/build_policies.py — edit the text there.
     tests/test_policy_pages.py fails if this file and that script differ. -->
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%232456d6'/%3E%3Cpath d='M8 9h7v14H8z' fill='%23ffffff'/%3E%3Cpath d='M17 9h7v14h-7z' fill='%23dbe4ff'/%3E%3C/svg%3E">
<link rel="stylesheet" href="{root}assets/style.css">
<script src="{root}assets/lang.js" data-page-lang="{lang}" data-root="{root}" data-page="{slug}/" data-entry=""></script>
<meta property="og:type" content="website">
<meta property="og:site_name" content="RS Pixel">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE}/assets/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:type" content="image/png">
<meta property="og:image:alt" content="RS Pixel — a lay-flat photo book opened across two pages">
<meta property="og:locale" content="{locale}">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="{url}">
{alts}
<link rel="alternate" hreflang="x-default" href="{SITE}/{slug}/">
</head>
<body>

<header class="site-header">
  <div class="wrap header-row">
    <a class="brand" href="{root}{dir_}">
      <svg class="brand-mark" width="26" height="26" viewBox="0 0 32 32" aria-hidden="true">
        <rect width="32" height="32" rx="7" fill="#2456d6"/>
        <path d="M8 9h7v14H8z" fill="#ffffff"/>
        <path d="M17 9h7v14h-7z" fill="#dbe4ff"/>
      </svg>
      RS Pixel
    </a>
    <nav class="site-nav" aria-label="Main">
      <a href="{root}{dir_}">{c["back"]}</a>
      <a href="{root}{dir_}{other}/">{c["other"][slug]}</a>
    </nav>
    <a class="btn btn-primary btn-small header-cta" href="{root}editor/">{c["create"]}</a>
  </div>
</header>

<main id="top" class="section">
  <div class="wrap policy-doc">
      <h1>{title.split(" — ")[0]}</h1>
      <p class="policy-updated">{c["updated"]}</p>
      <p class="lede">{intro}</p>
{body}
  </div>
</main>

<footer class="site-footer">
  <div class="wrap footer-grid">
    <nav class="f-col" aria-label="Contacts">
      <h3>{c["f_contacts"]}</h3>
{contacts}
    </nav>
    <nav class="f-col" aria-label="Language">
      <h3>{c["f_language"]}</h3>
      <span class="f-current">{native}</span>
{lang_links}
    </nav>
  </div>
  <div class="wrap f-bottom">{c["bottom"]}</div>
</footer>

<script src="{root}assets/funnel.js"></script>

</body>
</html>
"""


def outputs() -> dict[str, str]:
    return {f"{LANGS[lang][0]}{slug}/index.html": render(lang, slug)
            for slug in SLUGS for lang in LANGS}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    stale = []
    for rel, html in outputs().items():
        path = REPO / rel
        if path.exists() and path.read_text(encoding="utf-8") == html:
            continue
        stale.append(rel)
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(html, encoding="utf-8")
    for rel in stale:
        print(("stale: " if args.check else "wrote ") + rel)
    print(f"{len(stale)} page(s) {'differ' if args.check else 'written'}")
    return 1 if (stale and args.check) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
