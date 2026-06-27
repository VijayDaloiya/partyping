import os
import re
import sqlite3
import uuid

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - optional dependency for local dev
    psycopg = None
    dict_row = None

DB_PATH = os.path.join(os.path.dirname(__file__), "partybing.db")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def _is_postgres():
    return bool(DATABASE_URL and psycopg is not None)


def _translate_sql(sql):
    if not _is_postgres():
        return sql

    stripped = sql.strip()
    if stripped.upper().startswith("INSERT OR IGNORE INTO"):
        match = re.match(r"(?is)^\s*INSERT OR IGNORE INTO\s+(.*?)\s+VALUES\s*(\(.*\))\s*$", sql)
        if match:
            sql = f"INSERT INTO {match.group(1)} VALUES {match.group(2)} ON CONFLICT DO NOTHING"
    elif stripped.upper().startswith("INSERT OR REPLACE INTO SETTINGS"):
        match = re.match(r"(?is)^\s*INSERT OR REPLACE INTO\s+settings\s*\((.*?)\)\s+VALUES\s*(\(.*\))\s*$", sql)
        if match:
            sql = f"INSERT INTO settings ({match.group(1)}) VALUES {match.group(2)} ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"

    return sql.replace("?", "%s")


class _CursorProxy:
    def __init__(self, cursor):
        self._cursor = cursor

    @staticmethod
    def _wrap_row(row):
        if row is None or not isinstance(row, dict):
            return row
        class _RowProxy(dict):
            def __getitem__(self, item):
                if isinstance(item, int):
                    return list(self.values())[item]
                return super().__getitem__(item)
        return _RowProxy(row)

    def execute(self, sql, params=None):
        translated = _translate_sql(sql)
        self._cursor.execute(translated, params or ())
        return self

    def fetchone(self):
        return self._wrap_row(self._cursor.fetchone())

    def fetchall(self):
        return [self._wrap_row(row) for row in self._cursor.fetchall()]

    def close(self):
        self._cursor.close()


class _ConnectionProxy:
    def __init__(self, connection):
        self._connection = connection

    def cursor(self):
        return _CursorProxy(self._connection.cursor())

    def execute(self, sql, params=None):
        cursor = self.cursor()
        cursor.execute(sql, params)
        return cursor

    def commit(self):
        self._connection.commit()

    def close(self):
        self._connection.close()


def _create_table(cursor, sqlite_sql, postgres_sql):
    cursor.execute(postgres_sql if _is_postgres() else sqlite_sql)


def get_db():
    if _is_postgres():
        connection = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        return _ConnectionProxy(connection)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection

def _table_columns(cursor, table_name):
    if _is_postgres():
        rows = cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table_name,)
        ).fetchall()
        return {row["column_name"] for row in rows}
    rows = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}

def _ensure_gallery_columns(cursor):
    columns = _table_columns(cursor, "gallery")
    if "price" not in columns:
        cursor.execute("ALTER TABLE gallery ADD COLUMN price INTEGER" if not _is_postgres() else "ALTER TABLE gallery ADD COLUMN IF NOT EXISTS price INTEGER")
    if "discount_price" not in columns:
        cursor.execute("ALTER TABLE gallery ADD COLUMN discount_price INTEGER" if not _is_postgres() else "ALTER TABLE gallery ADD COLUMN IF NOT EXISTS discount_price INTEGER")
    if "code" not in columns:
        cursor.execute("ALTER TABLE gallery ADD COLUMN code TEXT" if not _is_postgres() else "ALTER TABLE gallery ADD COLUMN IF NOT EXISTS code TEXT")

def _ensure_gallery_code_index(cursor):
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_gallery_code ON gallery(code)")

def _ensure_gallery_images_table(cursor):
    _create_table(
        cursor,
        """CREATE TABLE IF NOT EXISTS gallery_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gallery_id INTEGER NOT NULL,
            image TEXT NOT NULL,
            display_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (gallery_id) REFERENCES gallery(id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS gallery_images (
            id SERIAL PRIMARY KEY,
            gallery_id INTEGER NOT NULL REFERENCES gallery(id) ON DELETE CASCADE,
            image TEXT NOT NULL,
            display_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
    )

def _normalize_code(value):
    text = (value or "").strip().upper()
    text = re.sub(r"[^A-Z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text

def _unique_gallery_code(cursor, desired, gallery_id=None):
    base = _normalize_code(desired) or f"PBG-{uuid.uuid4().hex[:8].upper()}"
    candidate = base
    suffix = 2
    while True:
        row = cursor.execute("SELECT id FROM gallery WHERE code=?", (candidate,)).fetchone()
        row_id = row["id"] if row and isinstance(row, dict) else (row[0] if row else None)
        if not row or (gallery_id is not None and row_id == gallery_id):
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1

def _backfill_gallery_columns(cursor):
    default_price_row = cursor.execute(
        "SELECT value FROM settings WHERE key='default_price'"
    ).fetchone()
    default_price = int(default_price_row["value"] if isinstance(default_price_row, dict) else default_price_row[0]) if default_price_row and (default_price_row["value"] if isinstance(default_price_row, dict) else default_price_row[0]) else 2499
    service_prices = {
        (row["id"] if isinstance(row, dict) else row[0]): (row["price"] if isinstance(row, dict) else row[1])
        for row in cursor.execute("SELECT id, price FROM services").fetchall()
    }
    gallery_rows = cursor.execute("SELECT id, service_id, price, discount_price, code FROM gallery").fetchall()
    for row in gallery_rows:
        row_id = row["id"] if isinstance(row, dict) else row[0]
        service_id = row["service_id"] if isinstance(row, dict) else row[1]
        current_price = row["price"] if isinstance(row, dict) else row[2]
        current_discount = row["discount_price"] if isinstance(row, dict) else row[3]
        current_code = row["code"] if isinstance(row, dict) else row[4]
        fallback_price = service_prices.get(service_id, default_price)
        price = current_price if current_price not in (None, 0, "") else fallback_price
        discount_price = current_discount if current_discount not in (None, 0, "") else price
        code = _unique_gallery_code(cursor, current_code or f"PBG-{row_id:05d}", gallery_id=row_id)
        cursor.execute(
            "UPDATE gallery SET price=?, discount_price=?, code=? WHERE id=?",
            (price, discount_price, code, row_id),
        )

def _row_value(row, key, index=0):
    if row is None:
        return None
    if isinstance(row, dict):
        return row[key]
    return row[index]

def _migrate_sqlite_snapshot_to_postgres(cursor):
    if not _is_postgres() or not os.path.exists(DB_PATH):
        return
    source = sqlite3.connect(DB_PATH)
    source.row_factory = sqlite3.Row
    tables = ["settings", "services", "localities", "blog_posts", "gallery", "gallery_images", "testimonials", "inquiries"]
    for table_name in tables:
        rows = source.execute(f"SELECT * FROM {table_name}").fetchall()
        if not rows:
            continue
        columns = rows[0].keys()
        placeholders = ", ".join(["?"] * len(columns))
        column_list = ", ".join(columns)
        for row in rows:
            values = [row[column] for column in columns]
            cursor.execute(f"INSERT INTO {table_name} ({column_list}) VALUES ({placeholders})", values)
    source.close()

    for table_name in ["services", "localities", "blog_posts", "gallery", "gallery_images", "testimonials", "inquiries"]:
        try:
            cursor.execute(
                f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {table_name}"
            )
        except Exception:
            pass

def init_db():
    conn = get_db()
    c = conn.cursor()

    _create_table(
        c,
        """CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )"""
    )

    _create_table(
        c,
        """CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            short_desc TEXT,
            description TEXT,
            price INTEGER DEFAULT 2499,
            image TEXT,
            meta_title TEXT,
            meta_description TEXT,
            faq TEXT,
            display_order INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS services (
            id SERIAL PRIMARY KEY,
            slug TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            short_desc TEXT,
            description TEXT,
            price INTEGER DEFAULT 2499,
            image TEXT,
            meta_title TEXT,
            meta_description TEXT,
            faq TEXT,
            display_order INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
    )

    _create_table(
        c,
        """CREATE TABLE IF NOT EXISTS localities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            meta_title TEXT,
            meta_description TEXT,
            is_active INTEGER DEFAULT 1
        )""",
        """CREATE TABLE IF NOT EXISTS localities (
            id SERIAL PRIMARY KEY,
            slug TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            meta_title TEXT,
            meta_description TEXT,
            is_active INTEGER DEFAULT 1
        )"""
    )

    _create_table(
        c,
        """CREATE TABLE IF NOT EXISTS blog_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            meta_title TEXT,
            meta_description TEXT,
            excerpt TEXT,
            content TEXT,
            image TEXT,
            tags TEXT,
            is_published INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS blog_posts (
            id SERIAL PRIMARY KEY,
            slug TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            meta_title TEXT,
            meta_description TEXT,
            excerpt TEXT,
            content TEXT,
            image TEXT,
            tags TEXT,
            is_published INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
    )

    _create_table(
        c,
        """CREATE TABLE IF NOT EXISTS gallery (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image TEXT NOT NULL,
            caption TEXT,
            service_id INTEGER,
            price INTEGER,
            discount_price INTEGER,
            code TEXT,
            display_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (service_id) REFERENCES services(id)
        )""",
        """CREATE TABLE IF NOT EXISTS gallery (
            id SERIAL PRIMARY KEY,
            image TEXT NOT NULL,
            caption TEXT,
            service_id INTEGER REFERENCES services(id),
            price INTEGER,
            discount_price INTEGER,
            code TEXT,
            display_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    _ensure_gallery_images_table(c)

    _create_table(
        c,
        """CREATE TABLE IF NOT EXISTS testimonials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            text TEXT NOT NULL,
            rating INTEGER DEFAULT 5,
            service TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS testimonials (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            text TEXT NOT NULL,
            rating INTEGER DEFAULT 5,
            service TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
    )

    _create_table(
        c,
        """CREATE TABLE IF NOT EXISTS inquiries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            service TEXT,
            event_date TEXT,
            locality TEXT,
            message TEXT,
            status TEXT DEFAULT 'new',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS inquiries (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            service TEXT,
            event_date TEXT,
            locality TEXT,
            message TEXT,
            status TEXT DEFAULT 'new',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
    )

    conn.commit()

    _ensure_gallery_columns(c)
    imported_snapshot = False
    if _is_postgres():
        existing_settings = c.execute("SELECT COUNT(*) AS count FROM settings").fetchone()
        if _row_value(existing_settings, "count") == 0:
            _migrate_sqlite_snapshot_to_postgres(c)
            imported_snapshot = True

    # Seed default settings
    defaults = {
        "business_name": "PartyBing",
        "tagline": "Chandigarh's Premium Party Decoration Service",
        "phone": "919503146681",
        "email": "partybing0008@gmail.com",
        "address": "Shop No.45, Savitry Tower, VIP Rd, Zirakpur, Punjab 140603",
        "whatsapp": "919503146681",
        "instagram": "",
        "facebook": "",
        "google_maps": "https://maps.google.com/?q=PartyBing+Decoration+Wakad+Chandigarh",
        "default_price": "2499",
        "admin_password": "partybing@2026",
    }
    if not imported_snapshot:
        for key, value in defaults.items():
            c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

    # Seed services
    services = [
        ("birthday-decoration", "Birthday Decoration", "Make your birthday magical with stunning balloon & themed decorations", "Transform your birthday celebration into an unforgettable experience. Our expert decorators create personalized setups with premium balloons, LED lights, flowers, and themed accessories. From kids' cartoon themes to elegant adult celebrations, we handle everything at your doorstep in Chandigarh.", 2499, "/static/images/birthday.svg"),
        ("balloon-decoration", "Balloon Decoration", "Premium balloon arches, bouquets & artistic arrangements for any occasion", "Elevate your event with our professional balloon decoration services. We specialize in balloon arches, organic garlands, helium bouquets, balloon walls, and custom sculptures. Available for birthdays, weddings, corporate events, and more across Chandigarh.", 2499, "/static/images/balloon.svg"),
        ("anniversary-decoration", "Anniversary Decoration", "Romantic & elegant decoration setups for your special milestone", "Celebrate your love story with our romantic anniversary decoration packages. We create intimate candlelit setups, rose petal arrangements, heart-shaped balloon displays, and elegant backdrops that make your anniversary truly special.", 3499, "/static/images/anniversary.svg"),
        ("baby-shower-decoration", "Baby Shower Decoration", "Adorable baby shower themes with premium decor elements", "Welcome your little one with our charming baby shower decorations. Choose from pastel themes, teddy bear setups, hot air balloon designs, and gender reveal arrangements. Every detail is crafted with love.", 2999, "/static/images/baby-shower.svg"),
        ("wedding-decoration", "Wedding Decoration", "Grand wedding & reception decoration that creates lasting memories", "Make your wedding day picture-perfect with our comprehensive decoration services. From mandap decoration to reception stage setup, floral arrangements to lighting design, we bring your wedding vision to life.", 9999, "/static/images/wedding.svg"),
        ("haldi-decoration", "Haldi Decoration", "Vibrant yellow-themed haldi ceremony setups", "Add color and joy to your haldi ceremony with our traditional yet trendy decoration packages. Marigold arrangements, yellow drapes, floral swings, and photo-worthy backdrops included.", 3999, "/static/images/haldi.svg"),
        ("naming-ceremony", "Naming Ceremony Decoration", "Beautiful cradle ceremony & naming function decoration", "Celebrate your baby's naming ceremony with our specially designed decoration packages. Elegant cradle setups, floral arrangements, themed backdrops, and balloon accents create the perfect setting.", 2999, "/static/images/naming.svg"),
        ("corporate-events", "Corporate Event Decoration", "Professional event decor for office parties, launches & conferences", "Impress your team and clients with our corporate event decoration services. We handle office celebrations, product launches, annual days, and conference setups with professional elegance.", 4999, "/static/images/corporate.svg"),
        ("ring-ceremony", "Ring Ceremony Decoration", "Elegant engagement & ring ceremony decoration setups", "Make your engagement day memorable with our stunning ring ceremony decorations. Romantic backdrops, floral arrangements, and elegant stage setups tailored to your style.", 4999, "/static/images/ring.svg"),
        ("kids-party", "Kids Birthday Party", "Fun cartoon themes, character decorations & activity setups for kids", "Create magical moments for your little ones with our kids party decoration packages. Popular themes include Cocomelon, Paw Patrol, Frozen, Unicorn, Dinosaur, and more!", 2499, "/static/images/kids.svg"),
    ]

    if not imported_snapshot:
        for s in services:
            c.execute("INSERT OR IGNORE INTO services (slug, name, short_desc, description, price, image) VALUES (?, ?, ?, ?, ?, ?)", s)

    # Seed localities
    localities = [
        ("wakad", "Wakad"),
        ("baner", "Baner"),
        ("hinjewadi", "Hinjewadi"),
        ("kothrud", "Kothrud"),
        ("hadapsar", "Hadapsar"),
        ("viman-nagar", "Viman Nagar"),
        ("kharadi", "Kharadi"),
        ("magarpatta", "Magarpatta"),
        ("pimpri-chinchwad", "Pimpri Chinchwad"),
        ("aundh", "Aundh"),
        ("shivaji-nagar", "Shivaji Nagar"),
        ("koregaon-park", "Koregaon Park"),
        ("kalyani-nagar", "Kalyani Nagar"),
        ("bavdhan", "Bavdhan"),
        ("ravet", "Ravet"),
        ("nigdi", "Nigdi"),
        ("pimple-saudagar", "Pimple Saudagar"),
        ("katraj", "Katraj"),
        ("undri", "Undri"),
        ("warje", "Warje"),
    ]

    if not imported_snapshot:
        for loc in localities:
            c.execute("INSERT OR IGNORE INTO localities (slug, name) VALUES (?, ?)", loc)

    # Seed blog posts
    blog_posts = [
        (
            "birthday-decoration-ideas-Chandigarh",
            "Top 10 Birthday Decoration Ideas in Chandigarh (2026)",
            "Top 10 Birthday Decoration Ideas in Chandigarh 2026 | PartyBing",
            "Looking for birthday decoration ideas in Chandigarh? Here are the top 10 trending themes for 2026 — from balloon arches to romantic room setups. Starting ₹2499.",
            "Discover the most popular birthday decoration trends in Chandigarh for 2026. From elegant balloon setups to themed parties, find the perfect idea for your celebration.",
            """<h2>Best Birthday Decoration Ideas for Chandigarh in 2026</h2>
<p>Planning a birthday celebration in Chandigarh? Whether it's a surprise for your partner, a milestone birthday for your parents, or a fun party for your kids, the right decoration can make all the difference. Here are the top 10 trending birthday decoration ideas in Chandigarh for 2026.</p>

<h3>1. Balloon Arch Entrance</h3>
<p>A stunning balloon arch at the entrance sets the mood instantly. Choose colors that match your theme — pastels for elegant parties, bright colors for kids' birthdays. Our balloon arches start at just ₹2499 in Chandigarh.</p>

<h3>2. Romantic Room Decoration</h3>
<p>Perfect for surprising your partner! Think rose petals, LED fairy lights, heart-shaped balloons, and candles. This is our most popular package in areas like Koregaon Park, Baner, and Viman Nagar.</p>

<h3>3. Neon Sign + Balloon Wall</h3>
<p>A custom neon sign saying "Happy Birthday" or the person's name against a balloon wall backdrop makes for Instagram-worthy photos. Trending heavily in Chandigarh's party scene.</p>

<h3>4. Themed Kids Party (Cocomelon, Paw Patrol, Frozen)</h3>
<p>Kids love character-themed decorations! We create complete setups with themed balloons, banners, table settings, and photo backdrops. Popular in Wakad, Hinjewadi, and Pimpri-Chinchwad.</p>

<h3>5. Ring Light + Flower Backdrop</h3>
<p>An elegant ring light surrounded by artificial flowers and fairy lights. Perfect for milestone birthdays (25th, 30th, 50th). Great for photo opportunities.</p>

<h3>6. Jungle Theme</h3>
<p>Green balloons, leaf garlands, and animal cutouts create a wild adventure! Perfect for 1st and 2nd birthday parties. Very popular among Chandigarh parents.</p>

<h3>7. Black & Gold Luxury Theme</h3>
<p>Sophisticated black and gold balloons, sequin backdrop, and champagne bottle balloons. Ideal for adult birthdays and milestone celebrations in upscale Chandigarh areas.</p>

<h3>8. Candlelight Dinner Setup</h3>
<p>Transform your terrace or living room into a romantic candlelight dinner spot. Includes table decoration, candle path, balloon canopy, and rose petals.</p>

<h3>9. Car Boot Decoration (Dikki Decoration)</h3>
<p>Surprise someone by decorating your car boot! Balloons, fairy lights, cake stand, and a photo frame. Unique and trending in Chandigarh for birthday surprises.</p>

<h3>10. Minimalist Pastel Theme</h3>
<p>Less is more! Soft pastel balloons, simple balloon garland, and clean aesthetics. Perfect for those who prefer understated elegance.</p>

<h2>Birthday Decoration Cost in Chandigarh</h2>
<p>At PartyBing, our birthday decoration packages start at <strong>₹2499</strong>. The final price depends on your theme, venue size, and customization. We offer doorstep service across all Chandigarh areas including Wakad, Baner, Hinjewadi, Kothrud, Hadapsar, and more.</p>

<h2>How to Book</h2>
<p>Simply WhatsApp us at <strong>+91 9503146681</strong> with your preferred date, location, and theme idea. We'll send you a custom quote within 30 minutes!</p>""",
            "birthday,decoration,Chandigarh,ideas,2026",
        ),
        (
            "balloon-decoration-cost-Chandigarh",
            "Balloon Decoration Cost in Chandigarh — Complete Price Guide (2026)",
            "Balloon Decoration Cost in Chandigarh 2026 — Price List | PartyBing",
            "Complete guide to balloon decoration prices in Chandigarh. From simple setups (₹1500) to grand arches (₹8000+). Transparent pricing, no hidden charges.",
            "Find out how much balloon decoration costs in Chandigarh. Complete price breakdown for birthday, wedding, and event balloon decorations.",
            """<h2>Balloon Decoration Price in Chandigarh — Full Breakdown</h2>
<p>One of the most common questions we get at PartyBing is "How much does balloon decoration cost in Chandigarh?" Here's a complete, transparent price guide for 2026.</p>

<h3>Basic Balloon Decoration (₹1500 - ₹2500)</h3>
<ul>
<li>Simple balloon bunches (25-50 balloons)</li>
<li>Basic color theme</li>
<li>Wall or ceiling decoration</li>
<li>Best for: Small home celebrations, room decoration</li>
</ul>

<h3>Standard Balloon Package (₹2499 - ₹4000)</h3>
<ul>
<li>Balloon arch OR balloon wall</li>
<li>50-100 premium balloons</li>
<li>LED fairy lights included</li>
<li>Custom color theme</li>
<li>Name/age foil balloons</li>
<li>Best for: Birthday parties, anniversaries</li>
</ul>

<h3>Premium Balloon Setup (₹4000 - ₹8000)</h3>
<ul>
<li>Large balloon arch + backdrop</li>
<li>100-200 balloons (chrome, pastel, or themed)</li>
<li>Organic balloon garland</li>
<li>Photo booth setup</li>
<li>Flower accents</li>
<li>Best for: Grand birthdays, baby showers, engagements</li>
</ul>

<h3>Grand Event Decoration (₹8000 - ₹15000+)</h3>
<ul>
<li>Full venue balloon decoration</li>
<li>Multiple balloon arches</li>
<li>Ceiling installations</li>
<li>Table centerpieces</li>
<li>Stage decoration</li>
<li>Best for: Weddings, corporate events, large parties</li>
</ul>

<h2>What Affects the Price?</h2>
<h3>1. Number of Balloons</h3>
<p>More balloons = higher cost. A simple arch needs 80-100 balloons, while a grand backdrop might need 200+.</p>

<h3>2. Type of Balloons</h3>
<p>Regular latex (₹10-15/pc), Chrome balloons (₹20-30/pc), Foil/shaped (₹50-150/pc), Helium-filled (₹80-120/pc).</p>

<h3>3. Venue Size & Location</h3>
<p>Larger venues need more material. We serve all Chandigarh areas — Wakad, Baner, Hinjewadi, Kothrud, Hadapsar, Viman Nagar, and more.</p>

<h3>4. Complexity of Design</h3>
<p>Organic garlands and sculptural designs take more time and skill than simple bunches.</p>

<h2>Why Choose PartyBing?</h2>
<ul>
<li>Transparent pricing — no hidden charges</li>
<li>Doorstep service across all Chandigarh</li>
<li>Professional setup team</li>
<li>Premium quality balloons (no deflating!)</li>
<li>Same-day booking available</li>
</ul>

<h2>Get a Custom Quote</h2>
<p>Every event is unique! WhatsApp us at <strong>+91 9503146681</strong> with your requirements and we'll share an exact quote within minutes.</p>""",
            "balloon,decoration,cost,price,Chandigarh,2026",
        ),
        (
            "best-party-decorators-wakad-Chandigarh",
            "Best Party Decorators in Wakad, Chandigarh — Top Rated (2026)",
            "Best Party Decorators in Wakad Chandigarh 2026 | PartyBing",
            "Looking for the best party decorator in Wakad, Chandigarh? PartyBing offers premium decoration services starting ₹2499. Doorstep setup, same-day booking.",
            "Find the top-rated party decorators in Wakad, Chandigarh. Professional balloon, birthday, and event decoration at your doorstep.",
            """<h2>Best Party Decoration Services in Wakad, Chandigarh</h2>
<p>Wakad has become one of Chandigarh's most vibrant residential areas, and with growing families and young professionals, the demand for quality party decoration services has skyrocketed. Whether you're celebrating a birthday, anniversary, baby shower, or any special occasion, here's your guide to getting the best decoration in Wakad.</p>

<h3>Why PartyBing is Wakad's Top Choice</h3>
<p>At PartyBing, we've decorated 500+ events across Chandigarh, with Wakad being one of our primary service areas. Here's why families in Wakad trust us:</p>
<ul>
<li><strong>Quick Delivery:</strong> Located near Wakad, our team reaches your doorstep fast</li>
<li><strong>Affordable:</strong> Premium decoration starting just ₹2499</li>
<li><strong>Flexible:</strong> We decorate homes, halls, terraces, and society clubhouses</li>
<li><strong>Same-day:</strong> Last minute plans? We accept same-day bookings</li>
<li><strong>Trusted:</strong> 4.9★ Google rating with verified reviews</li>
</ul>

<h3>Popular Services in Wakad</h3>
<h4>1. Birthday Decoration at Home</h4>
<p>The most booked service in Wakad! We transform your living room into a birthday paradise with balloon arches, LED lights, and themed setups. Popular in societies like Blue Ridge, Kolte Patil, and Bramha buildings.</p>

<h4>2. Balloon Decoration for Kids Parties</h4>
<p>Wakad has a huge young family population. Our kids' party decorations (Cocomelon, Paw Patrol, Unicorn themes) are always in demand. Starting ₹2499.</p>

<h4>3. Anniversary Surprise Decoration</h4>
<p>Romantic room setups with candles, roses, and heart balloons. Perfect for surprising your partner at home after work.</p>

<h4>4. Baby Shower & Naming Ceremony</h4>
<p>Pastel themes, teddy bear setups, and elegant cradle decorations for welcoming your little one.</p>

<h3>Venues We Cover in Wakad</h3>
<ul>
<li>Home/flat decorations (1BHK to 4BHK)</li>
<li>Society clubhouses and community halls</li>
<li>Restaurants and banquet halls</li>
<li>Terrace and garden setups</li>
<li>Office party decorations</li>
</ul>

<h3>Nearby Areas We Also Serve</h3>
<p>Besides Wakad, we provide decoration services in Hinjewadi, Pimple Saudagar, Baner, Balewadi, Ravet, and all surrounding areas.</p>

<h3>How to Book</h3>
<p>Getting your party decorated in Wakad is simple:</p>
<ol>
<li>WhatsApp us at <strong>+91 9503146681</strong></li>
<li>Share your date, theme preference, and budget</li>
<li>We'll send photos and a custom quote</li>
<li>Confirm booking with 50% advance</li>
<li>Our team arrives and sets up everything!</li>
</ol>

<h2>Book Now</h2>
<p>Don't wait — popular dates fill up fast in Wakad! Contact PartyBing today for the best decoration experience.</p>""",
            "party,decorator,wakad,Chandigarh,best,2026",
        ),
        (
            "haldi-decoration-ideas-at-home",
            "15 Beautiful Haldi Decoration Ideas at Home (2026 Trends)",
            "Haldi Decoration Ideas at Home 2026 | PartyBing Chandigarh",
            "Beautiful haldi ceremony decoration ideas for home. Marigold themes, photo backdrops, floral swings & more. Professional setup in Chandigarh starting ₹3999.",
            "Trending haldi decoration ideas you can recreate at home. From traditional marigold setups to modern Instagram-worthy designs.",
            """<h2>Trending Haldi Decoration Ideas for Home (2026)</h2>
<p>The haldi ceremony is one of the most joyful pre-wedding celebrations, and the right decoration makes it even more special. Here are 15 beautiful haldi decoration ideas that are trending in Chandigarh for 2026.</p>

<h3>1. Traditional Marigold Canopy</h3>
<p>Strings of fresh marigold flowers creating a canopy over the haldi area. Add some green mango leaves for a traditional touch. This is the most popular choice in Chandigarh.</p>

<h3>2. Yellow Drape Backdrop</h3>
<p>Flowing yellow and white drapes as a backdrop, decorated with marigold strings and fairy lights. Perfect for photos and the haldi ritual.</p>

<h3>3. Floral Swing (Jhula) Setup</h3>
<p>A decorated swing for the bride/groom to sit on during the ceremony. Adorned with fresh flowers, ribbons, and marigolds.</p>

<h3>4. Marigold Wall with Name</h3>
<p>A full wall covered in marigold flowers with the bride/groom's name spelled out in contrasting flowers or lights.</p>

<h3>5. Banana Leaf & Marigold Traditional</h3>
<p>Banana leaves, coconuts, and marigold strings for a completely traditional South Indian or Maharashtrian haldi setup.</p>

<h3>6. Sunflower Theme</h3>
<p>Mix sunflowers with marigolds for a modern twist on the traditional yellow theme. Bright, cheerful, and photo-worthy.</p>

<h3>7. Boho-Chic Haldi Setup</h3>
<p>Macrame hangings, dried flowers, pampas grass mixed with yellow elements. For the modern bride who wants something different.</p>

<h3>8. Umbrella Decoration</h3>
<p>Inverted yellow and orange umbrellas hanging from the ceiling with marigold strings. Creates a stunning visual effect.</p>

<h3>9. Photo Booth Corner</h3>
<p>A dedicated photo area with haldi-themed props — sunglasses, fun signs ("Haldi Hai!"), turmeric-colored frames.</p>

<h3>10. Terrace Garden Setup</h3>
<p>If you have a terrace, transform it into a haldi paradise with yellow carpet, potted marigolds, and fabric canopy.</p>

<h3>11. Mason Jar & Marigold Centerpieces</h3>
<p>Mason jars filled with marigolds as table centerpieces. Simple, elegant, and budget-friendly.</p>

<h3>12. Kite Decoration Theme</h3>
<p>Yellow kites hanging as decor elements along with marigold strings. Adds a playful Maharashtrian touch.</p>

<h3>13. Rangoli + Flower Carpet</h3>
<p>A large floor rangoli made with marigold petals, rose petals, and colored powder around the haldi area.</p>

<h3>14. LED Light Canopy</h3>
<p>Warm LED fairy lights creating a canopy effect over the ceremony area, combined with yellow drapes. Looks magical in evening ceremonies.</p>

<h3>15. Minimalist White & Yellow</h3>
<p>Clean white drapes with selective yellow flower accents. Modern, elegant, and clutter-free.</p>

<h2>Haldi Decoration Cost in Chandigarh</h2>
<p>At PartyBing, our haldi decoration packages start at <strong>₹3999</strong>. This includes backdrop, floor decoration, seating area setup, and basic flower arrangements. Premium packages with fresh flowers and extensive setups range from ₹5000-₹12000.</p>

<h2>Book Your Haldi Decoration</h2>
<p>WhatsApp us at <strong>+91 9503146681</strong> with your ceremony date and venue in Chandigarh. We'll create the perfect haldi setup for you!</p>""",
            "haldi,decoration,ideas,home,Chandigarh,2026",
        ),
        (
            "baby-shower-decoration-themes-Chandigarh",
            "Baby Shower Decoration Themes & Ideas in Chandigarh (2026)",
            "Baby Shower Decoration Ideas Chandigarh 2026 | PartyBing",
            "Beautiful baby shower decoration themes in Chandigarh. Pastel, teddy bear, hot air balloon & gender reveal setups. Doorstep service starting ₹2999.",
            "Explore trending baby shower decoration themes for 2026. From pastel elegance to fun gender reveals, find the perfect setup for your celebration in Chandigarh.",
            """<h2>Baby Shower Decoration Ideas & Themes in Chandigarh</h2>
<p>Expecting a little one? A beautifully decorated baby shower creates memories that last forever. Here are the most popular baby shower decoration themes trending in Chandigarh for 2026.</p>

<h3>Popular Baby Shower Themes</h3>

<h4>1. Pastel Dreams</h4>
<p>Soft pink, blue, lavender, and mint balloons with white accents. The most popular choice for baby showers in Chandigarh. Works perfectly for both genders.</p>

<h4>2. Teddy Bear Theme</h4>
<p>Adorable teddy bears, brown and cream balloons, and "We Can Bearly Wait" banner. A timeless classic that everyone loves.</p>

<h4>3. Hot Air Balloon Theme</h4>
<p>Miniature hot air balloon props, cloud-shaped balloons, and sky-blue backdrop. Whimsical and dreamy!</p>

<h4>4. Twinkle Twinkle Little Star</h4>
<p>Gold stars, moon props, navy blue backdrop with fairy lights. Perfect for evening celebrations.</p>

<h4>5. Elephant & Clouds</h4>
<p>Grey elephant cutouts, fluffy white cloud balloons, and soft blue/pink accents. Gender-neutral and adorable.</p>

<h4>6. Garden/Butterfly Theme</h4>
<p>Flower decorations, butterfly props, green and pink color palette. Fresh and beautiful for daytime celebrations.</p>

<h3>Gender Reveal Decoration</h3>
<p>Planning a gender reveal at your baby shower? We offer:</p>
<ul>
<li>Black balloon with pink/blue confetti inside</li>
<li>"He or She?" backdrop with reveal box</li>
<li>Pink vs Blue themed decoration split</li>
<li>Smoke bomb reveal setup (outdoor only)</li>
</ul>

<h3>What's Included in Our Baby Shower Package (₹2999)</h3>
<ul>
<li>Themed balloon arrangement (50+ balloons)</li>
<li>Backdrop with "Baby Shower" or custom text</li>
<li>Mom-to-be sash</li>
<li>LED fairy lights</li>
<li>Table decoration</li>
<li>Photo props</li>
</ul>

<h3>Premium Package (₹5000-₹8000)</h3>
<ul>
<li>Everything in basic package</li>
<li>Flower arrangements</li>
<li>Welcome board with baby name/theme</li>
<li>Ceiling decoration</li>
<li>Gift table setup</li>
<li>Photo booth corner</li>
</ul>

<h3>Venues We Decorate in Chandigarh</h3>
<p>We set up baby shower decorations at:</p>
<ul>
<li>Your home (most popular!)</li>
<li>Society clubhouses in Wakad, Baner, Hinjewadi</li>
<li>Restaurants and party halls</li>
<li>Hotels</li>
</ul>

<h2>Book Baby Shower Decoration in Chandigarh</h2>
<p>Contact PartyBing at <strong>+91 9503146681</strong> (WhatsApp) to book your baby shower decoration. We recommend booking 3-5 days in advance for the best experience!</p>""",
            "baby shower,decoration,themes,Chandigarh,2026",
        ),
    ]

    if not imported_snapshot:
        for post in blog_posts:
            c.execute("INSERT OR IGNORE INTO blog_posts (slug, title, meta_title, meta_description, excerpt, content, tags) VALUES (?,?,?,?,?,?,?)", post)

    # Seed testimonials
    testimonials = [
        ("Priya Sharma", "PartyBing did an amazing birthday decoration for my daughter's 5th birthday. The unicorn theme was perfect and the kids loved it! Very professional team.", 5, "Birthday Decoration"),
        ("Rahul Patil", "Booked them for our anniversary surprise. The romantic room setup with candles and roses was exactly what I wanted. Wife was thrilled!", 5, "Anniversary Decoration"),
        ("Sneha Joshi", "Used PartyBing for our baby shower. The pastel theme was gorgeous and they set up everything on time. Highly recommended in Chandigarh!", 5, "Baby Shower Decoration"),
        ("Amit Kulkarni", "Corporate annual day decoration was handled superbly. Professional, punctual, and the stage looked amazing. Will use again.", 5, "Corporate Events"),
        ("Meera Deshmukh", "The haldi decoration was so vibrant and beautiful. All our guests complimented the setup. Thank you PartyBing team!", 5, "Haldi Decoration"),
        ("Vikram Singh", "Balloon arch for my son's birthday party was outstanding. Great quality balloons and very creative design. Value for money!", 4, "Balloon Decoration"),
    ]

    if not imported_snapshot:
        for t in testimonials:
            c.execute("INSERT OR IGNORE INTO testimonials (name, text, rating, service) VALUES (?, ?, ?, ?)", t)

    _backfill_gallery_columns(c)
    _ensure_gallery_code_index(c)

    conn.commit()
    conn.close()

def get_setting(key):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None

def get_all_settings():
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {row["key"]: row["value"] for row in rows}
