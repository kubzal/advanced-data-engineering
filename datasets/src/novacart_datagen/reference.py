"""Statyczne dane referencyjne NovaCart: kraje, imiona, miasta, kategorie, marki, przewoźnicy.

Wszystkie marki, firmy i domeny e-mail są fikcyjne. Domeny e-mail używają zarezerwowanej
domeny najwyższego poziomu ``.example`` (RFC 2606), więc wygenerowane adresy nigdy nie trafią
do prawdziwej skrzynki.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Kraje
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class City:
    name: str
    weight: float  # przybliżona populacja w mln, używana jako waga losowania
    postal_prefix: str  # pierwsza cyfra kodu pocztowego


@dataclass(frozen=True)
class Country:
    code: str
    name_pl: str
    currency: str
    eur_rate: float  # ile jednostek waluty za 1 EUR (stały kurs na potrzeby generatora)
    weight: float  # udział w bazie klientów
    seller_weight: float  # udział w bazie sprzedawców
    phone_prefix: str
    mobile_prefixes: tuple[str, ...]
    phone_digits: int  # liczba cyfr po prefiksie komórkowym
    postal_format: str  # "#" = cyfra, "?" = wielka litera, "P" = prefiks miasta
    first_m: tuple[str, ...]
    first_f: tuple[str, ...]
    last: tuple[tuple[str, str], ...]  # (forma męska, forma żeńska)
    cities: tuple[City, ...]
    streets: tuple[str, ...]
    email_domains: tuple[tuple[str, float], ...]
    apartment_sep: str = "/"  # separator numeru mieszkania
    tz: str = "Europe/Warsaw"


def _same(*names: str) -> tuple[tuple[str, str], ...]:
    return tuple((n, n) for n in names)


COUNTRIES: tuple[Country, ...] = (
    Country(
        code="PL",
        name_pl="Polska",
        currency="PLN",
        eur_rate=4.30,
        weight=0.45,
        seller_weight=0.60,
        phone_prefix="+48",
        mobile_prefixes=("50", "51", "53", "57", "60", "66", "69", "72", "78", "79", "88"),
        phone_digits=7,
        postal_format="P#-###",
        first_m=(
            "Piotr",
            "Krzysztof",
            "Andrzej",
            "Tomasz",
            "Paweł",
            "Michał",
            "Marcin",
            "Jakub",
            "Kamil",
            "Łukasz",
            "Mateusz",
            "Adam",
            "Wojciech",
            "Szymon",
            "Bartosz",
            "Grzegorz",
        ),
        first_f=(
            "Anna",
            "Maria",
            "Katarzyna",
            "Małgorzata",
            "Agnieszka",
            "Barbara",
            "Ewa",
            "Magdalena",
            "Joanna",
            "Zofia",
            "Julia",
            "Natalia",
            "Aleksandra",
            "Monika",
            "Karolina",
            "Dorota",
        ),
        last=(
            ("Nowak", "Nowak"),
            ("Kowalski", "Kowalska"),
            ("Wiśniewski", "Wiśniewska"),
            ("Wójcik", "Wójcik"),
            ("Kowalczyk", "Kowalczyk"),
            ("Kamiński", "Kamińska"),
            ("Lewandowski", "Lewandowska"),
            ("Zieliński", "Zielińska"),
            ("Szymański", "Szymańska"),
            ("Woźniak", "Woźniak"),
            ("Dąbrowski", "Dąbrowska"),
            ("Kozłowski", "Kozłowska"),
            ("Jankowski", "Jankowska"),
            ("Mazur", "Mazur"),
            ("Kwiatkowski", "Kwiatkowska"),
            ("Krawczyk", "Krawczyk"),
            ("Piotrowski", "Piotrowska"),
            ("Grabowski", "Grabowska"),
            ("Nowakowski", "Nowakowska"),
            ("Pawłowski", "Pawłowska"),
            ("Michalski", "Michalska"),
            ("Król", "Król"),
            ("Wieczorek", "Wieczorek"),
            ("Jabłoński", "Jabłońska"),
            ("Wróbel", "Wróbel"),
            ("Majewski", "Majewska"),
        ),
        cities=(
            City("Warszawa", 1.86, "0"),
            City("Kraków", 0.80, "3"),
            City("Wrocław", 0.67, "5"),
            City("Łódź", 0.66, "9"),
            City("Poznań", 0.54, "6"),
            City("Gdańsk", 0.47, "8"),
            City("Szczecin", 0.39, "7"),
            City("Bydgoszcz", 0.33, "8"),
            City("Lublin", 0.33, "2"),
            City("Katowice", 0.29, "4"),
            City("Białystok", 0.29, "1"),
            City("Rzeszów", 0.20, "3"),
        ),
        streets=(
            "ul. Marszałkowska",
            "ul. Długa",
            "ul. Polna",
            "ul. Lipowa",
            "ul. Ogrodowa",
            "ul. Słoneczna",
            "ul. Mickiewicza",
            "ul. Kościuszki",
            "ul. Leśna",
            "ul. Szkolna",
            "ul. Kwiatowa",
            "ul. Piłsudskiego",
        ),
        email_domains=(
            ("gmail.example", 0.35),
            ("wp.example", 0.20),
            ("onet.example", 0.15),
            ("o2.example", 0.12),
            ("interia.example", 0.10),
            ("outlook.example", 0.08),
        ),
    ),
    Country(
        code="DE",
        name_pl="Niemcy",
        currency="EUR",
        eur_rate=1.0,
        weight=0.25,
        seller_weight=0.15,
        phone_prefix="+49",
        mobile_prefixes=("151", "152", "157", "160", "162", "170", "171", "172", "176"),
        phone_digits=8,
        postal_format="P####",
        first_m=(
            "Lukas",
            "Leon",
            "Finn",
            "Jonas",
            "Paul",
            "Felix",
            "Maximilian",
            "Elias",
            "Thomas",
            "Michael",
            "Stefan",
            "Andreas",
            "Jürgen",
            "Matthias",
        ),
        first_f=(
            "Mia",
            "Emma",
            "Hannah",
            "Sophia",
            "Lea",
            "Anna",
            "Laura",
            "Julia",
            "Sabine",
            "Katrin",
            "Petra",
            "Monika",
            "Ursula",
        ),
        last=_same(
            "Müller",
            "Schmidt",
            "Schneider",
            "Fischer",
            "Weber",
            "Meyer",
            "Wagner",
            "Becker",
            "Schulz",
            "Hoffmann",
            "Schäfer",
            "Koch",
            "Bauer",
            "Richter",
            "Klein",
            "Wolf",
            "Schröder",
            "Neumann",
            "Schwarz",
            "Zimmermann",
            "Braun",
            "Krüger",
        ),
        cities=(
            City("Berlin", 3.66, "1"),
            City("Hamburg", 1.85, "2"),
            City("München", 1.51, "8"),
            City("Köln", 1.08, "5"),
            City("Frankfurt am Main", 0.76, "6"),
            City("Stuttgart", 0.63, "7"),
            City("Düsseldorf", 0.62, "4"),
            City("Leipzig", 0.60, "0"),
            City("Dortmund", 0.59, "4"),
            City("Dresden", 0.56, "0"),
        ),
        streets=(
            "Hauptstraße",
            "Schulstraße",
            "Gartenstraße",
            "Bahnhofstraße",
            "Dorfstraße",
            "Bergstraße",
            "Lindenstraße",
            "Kirchstraße",
            "Waldstraße",
            "Ringstraße",
        ),
        email_domains=(
            ("gmail.example", 0.30),
            ("gmx.example", 0.25),
            ("web.example", 0.25),
            ("t-online.example", 0.10),
            ("outlook.example", 0.10),
        ),
        apartment_sep="",
        tz="Europe/Berlin",
    ),
    Country(
        code="CZ",
        name_pl="Czechy",
        currency="CZK",
        eur_rate=25.0,
        weight=0.12,
        seller_weight=0.10,
        phone_prefix="+420",
        mobile_prefixes=("601", "602", "603", "604", "605", "702", "720", "721", "731", "777"),
        phone_digits=6,
        postal_format="P## ##",
        first_m=("Jan", "Jakub", "Tomáš", "Petr", "Martin", "Lukáš", "Pavel", "Jiří", "David", "Ondřej"),
        first_f=(
            "Eliška",
            "Tereza",
            "Anna",
            "Adéla",
            "Natálie",
            "Jana",
            "Lucie",
            "Petra",
            "Kateřina",
            "Veronika",
        ),
        last=(
            ("Novák", "Nováková"),
            ("Svoboda", "Svobodová"),
            ("Novotný", "Novotná"),
            ("Dvořák", "Dvořáková"),
            ("Černý", "Černá"),
            ("Procházka", "Procházková"),
            ("Kučera", "Kučerová"),
            ("Veselý", "Veselá"),
            ("Horák", "Horáková"),
            ("Němec", "Němcová"),
            ("Pokorný", "Pokorná"),
            ("Marek", "Marková"),
        ),
        cities=(
            City("Praha", 1.33, "1"),
            City("Brno", 0.38, "6"),
            City("Ostrava", 0.28, "7"),
            City("Plzeň", 0.17, "3"),
            City("Liberec", 0.10, "4"),
            City("Olomouc", 0.10, "7"),
        ),
        streets=(
            "Hlavní",
            "Školní",
            "Nádražní",
            "Zahradní",
            "Krátká",
            "Polní",
            "Husova",
            "Komenského",
            "Palackého",
        ),
        email_domains=(("seznam.example", 0.50), ("gmail.example", 0.35), ("centrum.example", 0.15)),
        tz="Europe/Prague",
    ),
    Country(
        code="SK",
        name_pl="Słowacja",
        currency="EUR",
        eur_rate=1.0,
        weight=0.06,
        seller_weight=0.05,
        phone_prefix="+421",
        mobile_prefixes=("901", "902", "903", "904", "905", "910", "911", "915", "940", "948"),
        phone_digits=6,
        postal_format="P## ##",
        first_m=("Peter", "Martin", "Michal", "Jozef", "Ján", "Tomáš", "Lukáš", "Marek", "Juraj"),
        first_f=("Mária", "Zuzana", "Katarína", "Lucia", "Ivana", "Monika", "Veronika", "Simona"),
        last=(
            ("Horváth", "Horváthová"),
            ("Kováč", "Kováčová"),
            ("Varga", "Vargová"),
            ("Tóth", "Tóthová"),
            ("Nagy", "Nagyová"),
            ("Baláž", "Balážová"),
            ("Szabó", "Szabóová"),
            ("Molnár", "Molnárová"),
            ("Lukáč", "Lukáčová"),
            ("Kollár", "Kollárová"),
        ),
        cities=(
            City("Bratislava", 0.47, "8"),
            City("Košice", 0.23, "0"),
            City("Prešov", 0.09, "0"),
            City("Žilina", 0.08, "0"),
            City("Nitra", 0.08, "9"),
            City("Banská Bystrica", 0.07, "9"),
        ),
        streets=("Hlavná", "Školská", "Záhradná", "Krátka", "Štúrova", "Hviezdoslavova", "Mierová", "Nová"),
        email_domains=(("gmail.example", 0.45), ("azet.example", 0.30), ("centrum.example", 0.25)),
        tz="Europe/Bratislava",
    ),
    Country(
        code="LT",
        name_pl="Litwa",
        currency="EUR",
        eur_rate=1.0,
        weight=0.04,
        seller_weight=0.04,
        phone_prefix="+370",
        mobile_prefixes=("60", "61", "62", "64", "65", "67", "68", "69"),
        phone_digits=6,
        postal_format="LT-P####",
        first_m=("Lukas", "Matas", "Jonas", "Tomas", "Mantas", "Darius", "Andrius", "Paulius"),
        first_f=("Emilija", "Gabija", "Austėja", "Ieva", "Rūta", "Greta", "Laura", "Agnė"),
        last=(
            ("Kazlauskas", "Kazlauskienė"),
            ("Jankauskas", "Jankauskienė"),
            ("Petrauskas", "Petrauskienė"),
            ("Stankevičius", "Stankevičienė"),
            ("Vasiliauskas", "Vasiliauskienė"),
            ("Žukauskas", "Žukauskienė"),
            ("Butkus", "Butkienė"),
            ("Paulauskas", "Paulauskienė"),
        ),
        cities=(
            City("Vilnius", 0.59, "0"),
            City("Kaunas", 0.30, "4"),
            City("Klaipėda", 0.15, "9"),
            City("Šiauliai", 0.10, "7"),
            City("Panevėžys", 0.09, "3"),
        ),
        streets=(
            "Gedimino pr.",
            "Laisvės al.",
            "Vilniaus g.",
            "Liepų g.",
            "Ąžuolų g.",
            "Sodų g.",
            "Mokyklos g.",
            "Taikos pr.",
        ),
        email_domains=(("gmail.example", 0.60), ("inbox.example", 0.25), ("outlook.example", 0.15)),
        apartment_sep="-",
        tz="Europe/Vilnius",
    ),
    Country(
        code="NL",
        name_pl="Holandia",
        currency="EUR",
        eur_rate=1.0,
        weight=0.08,
        seller_weight=0.06,
        phone_prefix="+31",
        mobile_prefixes=("6",),
        phone_digits=8,
        postal_format="P### ??",
        first_m=("Daan", "Sem", "Lucas", "Levi", "Bram", "Jan", "Pieter", "Thijs", "Ruben"),
        first_f=("Emma", "Julia", "Sophie", "Lotte", "Anna", "Sanne", "Lisa", "Femke", "Eva"),
        last=_same(
            "de Jong",
            "Jansen",
            "de Vries",
            "van den Berg",
            "van Dijk",
            "Bakker",
            "Janssen",
            "Visser",
            "Smit",
            "Meijer",
            "de Boer",
            "Mulder",
            "de Groot",
            "Bos",
        ),
        cities=(
            City("Amsterdam", 0.92, "1"),
            City("Rotterdam", 0.66, "3"),
            City("Den Haag", 0.55, "2"),
            City("Utrecht", 0.36, "3"),
            City("Eindhoven", 0.24, "5"),
            City("Groningen", 0.23, "9"),
        ),
        streets=(
            "Kerkstraat",
            "Schoolstraat",
            "Molenstraat",
            "Dorpsstraat",
            "Stationsweg",
            "Julianastraat",
            "Wilhelminastraat",
            "Beatrixlaan",
        ),
        email_domains=(
            ("gmail.example", 0.40),
            ("outlook.example", 0.25),
            ("ziggo.example", 0.20),
            ("kpn.example", 0.15),
        ),
        apartment_sep="-",
        tz="Europe/Amsterdam",
    ),
)

COUNTRY_CODES: tuple[str, ...] = tuple(c.code for c in COUNTRIES)
CURRENCIES: tuple[str, ...] = tuple(c.currency for c in COUNTRIES)

# ---------------------------------------------------------------------------
# Kategorie produktów
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Leaf:
    slug: str
    name_pl: str
    name_en: str
    median_eur: float  # mediana ceny katalogowej w EUR
    sigma: float  # rozrzut (log-normalny) ceny
    weight_kg: float  # typowa waga przesyłki
    return_rate: float  # odsetek zwrotów
    nouns: tuple[str, ...]  # rdzenie nazw produktów (pełne frazy, by uniknąć problemów z odmianą)
    search_terms: tuple[str, ...]
    bulk: bool = False  # czy klienci często kupują wiele sztuk


@dataclass(frozen=True)
class TopCategory:
    slug: str
    name_pl: str
    name_en: str
    brands: tuple[str, ...]
    features: tuple[str, ...]  # cechy używane w opisach produktów (moduł 42, RAG)
    leaves: tuple[Leaf, ...] = field(default_factory=tuple)


CATEGORIES: tuple[TopCategory, ...] = (
    TopCategory(
        "elektronika",
        "Elektronika",
        "Electronics",
        brands=("Voltix", "Nexora", "Kirra", "Ampero", "Zentro"),
        features=(
            "długi czas pracy na baterii",
            "szybkie ładowanie",
            "łączność Bluetooth 5.3",
            "aktualizacje oprogramowania przez 5 lat",
            "energooszczędny tryb czuwania",
            "obudowa z aluminium z recyklingu",
            "24 miesiące gwarancji producenta",
        ),
        leaves=(
            Leaf(
                "smartfony",
                "Smartfony",
                "Smartphones",
                420,
                0.6,
                0.4,
                0.05,
                ("Smartfon", "Smartfon 5G", "Smartfon kompaktowy"),
                ("smartfon", "telefon 5g", "telefon z dobrym aparatem", "smartfon do 1500 zł"),
            ),
            Leaf(
                "laptopy",
                "Laptopy",
                "Laptops",
                850,
                0.5,
                2.5,
                0.05,
                ("Laptop", "Laptop ultrabook", "Laptop gamingowy"),
                ("laptop", "ultrabook", "laptop do gier", "laptop do pracy", "notebook 16 cali"),
            ),
            Leaf(
                "sluchawki",
                "Słuchawki",
                "Headphones",
                75,
                0.7,
                0.3,
                0.07,
                ("Słuchawki bezprzewodowe", "Słuchawki nauszne", "Słuchawki douszne ANC"),
                ("słuchawki", "słuchawki bezprzewodowe", "słuchawki z anc", "słuchawki do biegania"),
            ),
            Leaf(
                "telewizory",
                "Telewizory",
                "TVs",
                600,
                0.5,
                14.0,
                0.04,
                ("Telewizor 4K", "Telewizor OLED", "Telewizor QLED"),
                ("telewizor", "tv 55 cali", "telewizor oled", "smart tv"),
            ),
            Leaf(
                "akcesoria-komputerowe",
                "Akcesoria komputerowe",
                "Computer accessories",
                35,
                0.8,
                0.5,
                0.06,
                (
                    "Mysz bezprzewodowa",
                    "Klawiatura mechaniczna",
                    "Stacja dokująca USB-C",
                    "Kamera internetowa",
                ),
                ("mysz", "klawiatura mechaniczna", "hub usb-c", "kamerka do laptopa"),
            ),
        ),
    ),
    TopCategory(
        "dom-i-ogrod",
        "Dom i ogród",
        "Home & garden",
        brands=("Nordhaus", "Lumio", "Brikka", "Verdano", "Holmfeld"),
        features=(
            "łatwy montaż bez specjalistycznych narzędzi",
            "materiały z certyfikatem FSC",
            "odporność na wilgoć",
            "minimalistyczny skandynawski design",
            "możliwość mycia w zmywarce",
            "5 lat gwarancji",
        ),
        leaves=(
            Leaf(
                "meble",
                "Meble",
                "Furniture",
                180,
                0.7,
                25.0,
                0.08,
                ("Regał na książki", "Biurko z regulacją wysokości", "Krzesło biurowe", "Komoda"),
                ("regał", "biurko elektryczne", "krzesło ergonomiczne", "komoda biała"),
            ),
            Leaf(
                "oswietlenie",
                "Oświetlenie",
                "Lighting",
                40,
                0.7,
                1.5,
                0.06,
                ("Lampa stojąca", "Lampka biurkowa LED", "Żarówka smart"),
                ("lampa stojąca", "lampka led", "żarówka wifi", "oświetlenie salonu"),
            ),
            Leaf(
                "narzedzia",
                "Narzędzia",
                "Tools",
                65,
                0.8,
                3.0,
                0.04,
                ("Wiertarko-wkrętarka", "Zestaw kluczy", "Szlifierka kątowa"),
                ("wkrętarka", "zestaw narzędzi", "szlifierka", "wiertarka udarowa"),
            ),
            Leaf(
                "ogrod",
                "Ogród",
                "Garden",
                55,
                0.9,
                6.0,
                0.05,
                ("Kosiarka akumulatorowa", "Wąż ogrodowy", "Grill węglowy", "Zestaw mebli ogrodowych"),
                ("kosiarka", "wąż ogrodowy 30m", "grill", "meble ogrodowe"),
            ),
            Leaf(
                "dekoracje",
                "Dekoracje",
                "Decor",
                22,
                0.7,
                1.0,
                0.07,
                ("Świeca zapachowa", "Wazon ceramiczny", "Rama na zdjęcia", "Poduszka dekoracyjna"),
                ("świeca zapachowa", "wazon", "ramka na zdjęcia", "poduszki dekoracyjne"),
            ),
        ),
    ),
    TopCategory(
        "moda",
        "Moda",
        "Fashion",
        brands=("Mirelle", "Urbano", "Kalmo", "Vesta", "Noir & Co"),
        features=(
            "bawełna organiczna",
            "krój regular fit",
            "szwy wzmocnione w miejscach narażonych na przetarcia",
            "można prać w 30°C",
            "produkcja w Unii Europejskiej",
            "oddychający materiał",
        ),
        leaves=(
            Leaf(
                "odziez-damska",
                "Odzież damska",
                "Women's clothing",
                35,
                0.6,
                0.5,
                0.22,
                ("Sukienka midi", "Bluzka z wiskozy", "Spodnie szerokie", "Kurtka przejściowa damska"),
                ("sukienka", "bluzka damska", "spodnie damskie", "kurtka damska"),
            ),
            Leaf(
                "odziez-meska",
                "Odzież męska",
                "Men's clothing",
                38,
                0.6,
                0.6,
                0.18,
                ("Koszula slim fit", "Bluza z kapturem", "Spodnie chino", "Kurtka zimowa męska"),
                ("koszula męska", "bluza", "chinosy", "kurtka zimowa"),
            ),
            Leaf(
                "obuwie",
                "Obuwie",
                "Shoes",
                60,
                0.5,
                1.2,
                0.25,
                ("Sneakersy", "Buty trekkingowe", "Botki skórzane", "Klapki basenowe"),
                ("sneakersy", "buty trekkingowe", "botki", "buty do biegania"),
            ),
            Leaf(
                "torby-plecaki",
                "Torby i plecaki",
                "Bags & backpacks",
                45,
                0.6,
                0.8,
                0.12,
                ("Plecak miejski", "Torba na laptopa", "Torebka listonoszka"),
                ("plecak", "torba na laptopa", "torebka", "plecak 30l"),
            ),
            Leaf(
                "bizuteria",
                "Biżuteria",
                "Jewellery",
                30,
                0.9,
                0.1,
                0.10,
                ("Naszyjnik srebrny", "Kolczyki", "Bransoletka", "Zegarek"),
                ("naszyjnik", "kolczyki srebrne", "bransoletka", "zegarek damski"),
            ),
        ),
    ),
    TopCategory(
        "zdrowie-i-uroda",
        "Zdrowie i uroda",
        "Health & beauty",
        brands=("Floralis", "Pureva", "Aquilla", "Somnia", "Vitalio"),
        features=(
            "formuła wegańska",
            "przebadane dermatologicznie",
            "bez parabenów",
            "opakowanie nadające się do recyklingu",
            "do każdego rodzaju skóry",
        ),
        leaves=(
            Leaf(
                "kosmetyki",
                "Kosmetyki",
                "Cosmetics",
                14,
                0.6,
                0.3,
                0.03,
                ("Krem nawilżający", "Serum z witaminą C", "Podkład matujący", "Tusz do rzęs"),
                ("krem do twarzy", "serum", "podkład", "tusz do rzęs"),
            ),
            Leaf(
                "perfumy",
                "Perfumy",
                "Fragrances",
                45,
                0.6,
                0.4,
                0.03,
                ("Woda perfumowana", "Woda toaletowa"),
                ("perfumy damskie", "perfumy męskie", "woda toaletowa"),
            ),
            Leaf(
                "suplementy",
                "Suplementy",
                "Supplements",
                12,
                0.5,
                0.2,
                0.02,
                ("Witamina D3", "Magnez z B6", "Kolagen w proszku", "Omega-3"),
                ("witamina d", "magnez", "kolagen", "omega 3"),
                bulk=True,
            ),
            Leaf(
                "higiena",
                "Higiena",
                "Hygiene",
                8,
                0.6,
                0.6,
                0.01,
                ("Szczoteczka soniczna", "Pasta do zębów", "Żel pod prysznic"),
                ("szczoteczka elektryczna", "pasta do zębów", "żel pod prysznic"),
                bulk=True,
            ),
        ),
    ),
    TopCategory(
        "dziecko",
        "Dziecko",
        "Kids & baby",
        brands=("Zabawix", "Malucho", "Kidora", "Tinyland"),
        features=(
            "certyfikat bezpieczeństwa CE",
            "bez BPA",
            "dla dzieci od 3 lat",
            "łatwe do utrzymania w czystości",
            "rozwija kreatywność",
        ),
        leaves=(
            Leaf(
                "zabawki",
                "Zabawki",
                "Toys",
                25,
                0.7,
                1.0,
                0.04,
                ("Klocki konstrukcyjne", "Lalka", "Zestaw kreatywny", "Samochód zdalnie sterowany"),
                ("klocki", "lalka", "zabawki kreatywne", "auto zdalnie sterowane"),
            ),
            Leaf(
                "odziez-dziecieca",
                "Odzież dziecięca",
                "Kids' clothing",
                18,
                0.5,
                0.3,
                0.15,
                ("Body niemowlęce", "Kombinezon zimowy", "Piżama dziecięca"),
                ("body", "kombinezon zimowy", "piżama dla dziecka"),
                bulk=True,
            ),
            Leaf(
                "wozki-foteliki",
                "Wózki i foteliki",
                "Strollers & car seats",
                260,
                0.5,
                12.0,
                0.06,
                ("Wózek spacerowy", "Fotelik samochodowy", "Wózek wielofunkcyjny"),
                ("wózek", "fotelik samochodowy", "wózek 3w1"),
            ),
        ),
    ),
    TopCategory(
        "sport",
        "Sport i turystyka",
        "Sports & outdoors",
        brands=("Trailon", "Kinetiq", "Alpinea", "Strivo"),
        features=(
            "lekka konstrukcja",
            "materiał odporny na warunki atmosferyczne",
            "ergonomiczny kształt",
            "przetestowane przez profesjonalnych sportowców",
        ),
        leaves=(
            Leaf(
                "rowery",
                "Rowery",
                "Bicycles",
                520,
                0.5,
                16.0,
                0.03,
                ("Rower górski", "Rower miejski", "Rower gravel", "Rower elektryczny"),
                ("rower", "rower górski", "rower elektryczny", "gravel"),
            ),
            Leaf(
                "fitness",
                "Fitness",
                "Fitness",
                30,
                0.8,
                4.0,
                0.05,
                ("Mata do jogi", "Hantle regulowane", "Gumy oporowe", "Opaska sportowa"),
                ("mata do jogi", "hantle", "gumy oporowe", "opaska fitness"),
            ),
            Leaf(
                "turystyka",
                "Turystyka",
                "Hiking & camping",
                70,
                0.7,
                2.5,
                0.06,
                ("Namiot 2-osobowy", "Śpiwór puchowy", "Kijki trekkingowe", "Plecak trekkingowy"),
                ("namiot", "śpiwór", "kijki trekkingowe", "plecak turystyczny"),
            ),
            Leaf(
                "sporty-zimowe",
                "Sporty zimowe",
                "Winter sports",
                150,
                0.6,
                5.0,
                0.05,
                ("Narty zjazdowe", "Kask narciarski", "Gogle narciarskie", "Deska snowboardowa"),
                ("narty", "kask narciarski", "gogle", "snowboard"),
            ),
        ),
    ),
    TopCategory(
        "motoryzacja",
        "Motoryzacja",
        "Automotive",
        brands=("Autonix", "Drivo", "Torqa", "Roadline"),
        features=(
            "pasuje do większości modeli samochodów",
            "zgodne z normą ECE",
            "prosta instalacja",
            "wysoka odporność na temperaturę",
        ),
        leaves=(
            Leaf(
                "czesci-samochodowe",
                "Części samochodowe",
                "Car parts",
                55,
                0.9,
                3.0,
                0.08,
                ("Klocki hamulcowe", "Filtr oleju", "Akumulator samochodowy", "Wycieraczki"),
                ("klocki hamulcowe", "filtr oleju", "akumulator 74ah", "wycieraczki"),
            ),
            Leaf(
                "opony",
                "Opony",
                "Tyres",
                85,
                0.4,
                9.0,
                0.03,
                ("Opona letnia", "Opona zimowa", "Opona całoroczna"),
                ("opony zimowe", "opony letnie", "opony całoroczne 16"),
                bulk=True,
            ),
            Leaf(
                "akcesoria-samochodowe",
                "Akcesoria samochodowe",
                "Car accessories",
                25,
                0.8,
                0.8,
                0.05,
                ("Uchwyt na telefon", "Wideorejestrator", "Ładowarka samochodowa"),
                ("uchwyt na telefon", "kamera samochodowa", "ładowarka samochodowa"),
            ),
        ),
    ),
    TopCategory(
        "kultura-i-rozrywka",
        "Kultura i rozrywka",
        "Books & entertainment",
        brands=("Wydawnictwo Kreska", "Pixelforge", "Nutka Records", "Planszolandia"),
        features=(
            "polska wersja językowa",
            "wydanie kolekcjonerskie",
            "idealne na prezent",
            "dla 2–6 graczy",
            "twarda oprawa",
        ),
        leaves=(
            Leaf(
                "ksiazki",
                "Książki",
                "Books",
                12,
                0.4,
                0.5,
                0.02,
                ("Powieść kryminalna", "Poradnik", "Książka fantasy", "Biografia"),
                ("kryminał", "książka fantasy", "poradnik", "biografia"),
            ),
            Leaf(
                "gry-wideo",
                "Gry wideo",
                "Video games",
                45,
                0.4,
                0.2,
                0.03,
                ("Gra akcji", "Gra RPG", "Gra sportowa", "Gra strategiczna"),
                ("gra rpg", "gra na konsolę", "gra strategiczna", "gra sportowa"),
            ),
            Leaf(
                "muzyka",
                "Muzyka",
                "Music",
                18,
                0.4,
                0.2,
                0.02,
                ("Płyta winylowa", "Płyta CD", "Box kolekcjonerski"),
                ("winyl", "płyta cd", "box kolekcjonerski"),
            ),
            Leaf(
                "planszowki",
                "Gry planszowe",
                "Board games",
                32,
                0.5,
                1.2,
                0.03,
                ("Gra planszowa strategiczna", "Gra imprezowa", "Gra kooperacyjna"),
                ("gra planszowa", "gra imprezowa", "planszówka dla dwojga"),
            ),
        ),
    ),
    TopCategory(
        "supermarket",
        "Supermarket",
        "Grocery",
        brands=("Smakosz", "Aromatica", "Czystek"),
        features=(
            "produkt w opakowaniu zbiorczym",
            "długi termin przydatności",
            "certyfikat Fairtrade",
            "bez sztucznych barwników",
        ),
        leaves=(
            Leaf(
                "kawa-herbata",
                "Kawa i herbata",
                "Coffee & tea",
                11,
                0.5,
                1.0,
                0.01,
                ("Kawa ziarnista", "Herbata zielona", "Kawa mielona", "Kapsułki kawowe"),
                ("kawa ziarnista", "herbata", "kapsułki", "kawa 1kg"),
                bulk=True,
            ),
            Leaf(
                "slodycze",
                "Słodycze",
                "Sweets",
                5,
                0.5,
                0.5,
                0.01,
                ("Czekolada gorzka", "Baton proteinowy", "Żelki owocowe"),
                ("czekolada", "batony", "żelki"),
                bulk=True,
            ),
            Leaf(
                "chemia-domowa",
                "Chemia domowa",
                "Household cleaning",
                9,
                0.5,
                2.0,
                0.01,
                ("Kapsułki do prania", "Płyn do naczyń", "Tabletki do zmywarki"),
                ("kapsułki do prania", "płyn do naczyń", "tabletki do zmywarki"),
                bulk=True,
            ),
        ),
    ),
    TopCategory(
        "zwierzeta",
        "Zwierzęta",
        "Pets",
        brands=("Pazurek", "Mruczek", "Hau&Miau"),
        features=(
            "wysoka zawartość mięsa",
            "bez zbóż",
            "zalecane przez weterynarzy",
            "materiał odporny na pogryzienie",
        ),
        leaves=(
            Leaf(
                "karma",
                "Karma",
                "Pet food",
                28,
                0.6,
                7.0,
                0.01,
                ("Karma sucha dla psa", "Karma mokra dla kota", "Przysmaki dla psa"),
                ("karma dla psa", "karma dla kota", "przysmaki"),
                bulk=True,
            ),
            Leaf(
                "akcesoria-dla-zwierzat",
                "Akcesoria dla zwierząt",
                "Pet accessories",
                20,
                0.7,
                1.5,
                0.05,
                ("Legowisko dla psa", "Drapak dla kota", "Smycz automatyczna", "Kuweta"),
                ("legowisko", "drapak", "smycz", "kuweta"),
            ),
        ),
    ),
)


@dataclass(frozen=True)
class FlatCategory:
    category_id: int
    parent_id: int | None
    slug: str
    name_pl: str
    name_en: str
    top_index: int
    leaf: Leaf | None


def flatten_categories() -> list[FlatCategory]:
    """Zwraca płaską listę kategorii (najpierw kategorie główne, potem liście)."""
    flat: list[FlatCategory] = []
    for ti, top in enumerate(CATEGORIES):
        flat.append(FlatCategory(ti + 1, None, top.slug, top.name_pl, top.name_en, ti, None))
    next_id = 100
    for ti, top in enumerate(CATEGORIES):
        for leaf in top.leaves:
            flat.append(FlatCategory(next_id, ti + 1, leaf.slug, leaf.name_pl, leaf.name_en, ti, leaf))
            next_id += 1
    return flat


FLAT_CATEGORIES: list[FlatCategory] = flatten_categories()
LEAVES: list[FlatCategory] = [c for c in FLAT_CATEGORIES if c.leaf is not None]

# ---------------------------------------------------------------------------
# Sprzedawcy, przewoźnicy, inne słowniki
# ---------------------------------------------------------------------------

SELLER_WORDS = (
    "Bałtyk",
    "Mazowsze",
    "Wisła",
    "Tatry",
    "Karpaty",
    "Odra",
    "Polaris",
    "Nordic",
    "Alpen",
    "Danube",
    "Amber",
    "Silesia",
    "Pomorze",
    "Vltava",
    "Rhein",
    "Neman",
    "Delta",
    "Orbit",
    "Sokół",
    "Żubr",
    "Kometa",
    "Horyzont",
    "Promyk",
    "Euro",
    "Prima",
    "Atlas",
)
SELLER_SUFFIXES = {
    "PL": ("Trade sp. z o.o.", "Store sp. z o.o.", "Dystrybucja S.A.", "Sklep s.c.", "Hurt sp.j."),
    "DE": ("Handel GmbH", "Shop GmbH", "Vertrieb GmbH & Co. KG", "Waren AG"),
    "CZ": ("Obchod s.r.o.", "Trade s.r.o.", "Distribuce a.s."),
    "SK": ("Obchod s.r.o.", "Trade s.r.o."),
    "LT": ("Prekyba UAB", "Trade UAB"),
    "NL": ("Handel B.V.", "Shop B.V."),
}
SELLER_TIERS = ("standard", "pro", "premium")

PLATFORMS = ("web", "android", "ios")
PAYMENT_METHODS = ("card", "blik", "paypal", "bank_transfer", "ideal", "cod")
# Rozkład metod płatności per kraj (kolejność jak PAYMENT_METHODS)
PAYMENT_MIX = {
    "PL": (0.28, 0.45, 0.10, 0.10, 0.00, 0.07),
    "DE": (0.40, 0.00, 0.35, 0.15, 0.00, 0.10),
    "CZ": (0.50, 0.00, 0.10, 0.20, 0.00, 0.20),
    "SK": (0.50, 0.00, 0.15, 0.15, 0.00, 0.20),
    "LT": (0.55, 0.00, 0.20, 0.20, 0.00, 0.05),
    "NL": (0.20, 0.00, 0.20, 0.05, 0.50, 0.05),
}
PAYMENT_SUCCESS = {
    "card": 0.92,
    "blik": 0.97,
    "paypal": 0.96,
    "bank_transfer": 0.99,
    "ideal": 0.97,
    "cod": 1.0,
}
CARD_BRANDS = (("visa", 0.55), ("mastercard", 0.40), ("amex", 0.05))
FAILURE_CODES = ("card_declined", "insufficient_funds", "expired_card", "authentication_failed", "timeout")

PROMO_CODES = ("WELCOME10", "BLACKFRIDAY", "XMAS2025", "FREESHIP", "SPRING15", "APPONLY", "NEWSLETTER5")

CARRIERS = ("speedpost", "europarcel", "quickship")
# Prawdopodobieństwo wyboru przewoźnika w zależności od kraju dostawy
CARRIER_MIX = {
    "PL": (0.60, 0.40, 0.00),
    "DE": (0.00, 0.50, 0.50),
    "CZ": (0.10, 0.45, 0.45),
    "SK": (0.10, 0.45, 0.45),
    "LT": (0.20, 0.60, 0.20),
    "NL": (0.00, 0.50, 0.50),
}
CARRIER_HUBS = {
    "speedpost": (("Stryków", "PL"), ("Warszawa", "PL"), ("Poznań", "PL"), ("Katowice", "PL")),
    "europarcel": (("Berlin", "DE"), ("Praha", "CZ"), ("Wrocław", "PL"), ("Hamburg", "DE")),
    "quickship": (("Leipzig", "DE"), ("Brno", "CZ"), ("Utrecht", "NL"), ("Hamburg", "DE")),
}

TRAFFIC_SOURCES = (
    # (utm_source, utm_medium, referrer, waga)
    (None, None, None, 0.30),
    ("google", "organic", "https://www.google.com/", 0.25),
    ("google", "cpc", "https://www.google.com/", 0.15),
    ("facebook", "paid_social", "https://m.facebook.com/", 0.10),
    ("newsletter", "email", None, 0.08),
    ("tiktok", "paid_social", "https://www.tiktok.com/", 0.05),
    ("criteo", "display", None, 0.04),
    ("partner", "affiliate", "https://porownywarka.example/", 0.03),
)
CAMPAIGNS = ("always_on", "black_friday", "xmas", "spring_sale", "app_install", "retargeting")

USER_AGENTS = {
    "web": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
    ),
    "android": (
        "NovaCartApp/{v} (Android 14; Pixel 8)",
        "NovaCartApp/{v} (Android 13; SM-A546B)",
        "NovaCartApp/{v} (Android 15; SM-S921B)",
        "NovaCartApp/{v} (Android 12; Redmi Note 11)",
    ),
    "ios": (
        "NovaCartApp/{v} (iOS 18.1; iPhone15,2)",
        "NovaCartApp/{v} (iOS 17.6; iPhone14,5)",
        "NovaCartApp/{v} (iOS 18.0; iPhone16,1)",
    ),
}
IP_FIRST_OCTETS = (
    31,
    37,
    46,
    77,
    78,
    79,
    80,
    81,
    83,
    85,
    86,
    87,
    88,
    89,
    91,
    93,
    94,
    95,
    176,
    178,
    185,
    188,
    193,
    194,
    195,
    212,
    213,
    217,
)

COLORS = ("czarny", "biały", "szary", "granatowy", "czerwony", "zielony", "beżowy", "niebieski")

# ---------------------------------------------------------------------------
# Pomocnicze
# ---------------------------------------------------------------------------

_TRANSLIT = str.maketrans(
    {"ł": "l", "Ł": "L", "ß": "ss", "ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"}
)


def ascii_fold(text: str) -> str:
    """Transliteracja do ASCII na potrzeby adresów e-mail (``Łukasz Wiśniewski`` → ``Lukasz Wisniewski``)."""
    text = text.translate(_TRANSLIT)
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def email_token(text: str) -> str:
    return ascii_fold(text).lower().replace(" ", "").replace("'", "")
