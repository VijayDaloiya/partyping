import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "partybing.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS services (
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
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS localities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        meta_title TEXT,
        meta_description TEXT,
        is_active INTEGER DEFAULT 1
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS gallery (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        image TEXT NOT NULL,
        caption TEXT,
        service_id INTEGER,
        display_order INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (service_id) REFERENCES services(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS testimonials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        text TEXT NOT NULL,
        rating INTEGER DEFAULT 5,
        service TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS inquiries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT NOT NULL,
        service TEXT,
        event_date TEXT,
        locality TEXT,
        message TEXT,
        status TEXT DEFAULT 'new',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    conn.commit()

    # Seed default settings
    defaults = {
        "business_name": "PartyBing",
        "tagline": "Pune's Premium Party Decoration Service",
        "phone": "919503146681",
        "email": "partybing0008@gmail.com",
        "address": "Shop No. 4, Pristic Arcade, Wakad, Pimpri-Chinchwad, Pune 411057",
        "whatsapp": "919503146681",
        "instagram": "",
        "facebook": "",
        "google_maps": "https://maps.google.com/?q=PartyBing+Decoration+Wakad+Pune",
        "default_price": "2499",
        "admin_password": "partybing@2026",
    }
    for key, value in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

    # Seed services
    services = [
        ("birthday-decoration", "Birthday Decoration", "Make your birthday magical with stunning balloon & themed decorations", "Transform your birthday celebration into an unforgettable experience. Our expert decorators create personalized setups with premium balloons, LED lights, flowers, and themed accessories. From kids' cartoon themes to elegant adult celebrations, we handle everything at your doorstep in Pune.", 2499, "/static/images/birthday.svg"),
        ("balloon-decoration", "Balloon Decoration", "Premium balloon arches, bouquets & artistic arrangements for any occasion", "Elevate your event with our professional balloon decoration services. We specialize in balloon arches, organic garlands, helium bouquets, balloon walls, and custom sculptures. Available for birthdays, weddings, corporate events, and more across Pune.", 2499, "/static/images/balloon.svg"),
        ("anniversary-decoration", "Anniversary Decoration", "Romantic & elegant decoration setups for your special milestone", "Celebrate your love story with our romantic anniversary decoration packages. We create intimate candlelit setups, rose petal arrangements, heart-shaped balloon displays, and elegant backdrops that make your anniversary truly special.", 3499, "/static/images/anniversary.svg"),
        ("baby-shower-decoration", "Baby Shower Decoration", "Adorable baby shower themes with premium decor elements", "Welcome your little one with our charming baby shower decorations. Choose from pastel themes, teddy bear setups, hot air balloon designs, and gender reveal arrangements. Every detail is crafted with love.", 2999, "/static/images/baby-shower.svg"),
        ("wedding-decoration", "Wedding Decoration", "Grand wedding & reception decoration that creates lasting memories", "Make your wedding day picture-perfect with our comprehensive decoration services. From mandap decoration to reception stage setup, floral arrangements to lighting design, we bring your wedding vision to life.", 9999, "/static/images/wedding.svg"),
        ("haldi-decoration", "Haldi Decoration", "Vibrant yellow-themed haldi ceremony setups", "Add color and joy to your haldi ceremony with our traditional yet trendy decoration packages. Marigold arrangements, yellow drapes, floral swings, and photo-worthy backdrops included.", 3999, "/static/images/haldi.svg"),
        ("naming-ceremony", "Naming Ceremony Decoration", "Beautiful cradle ceremony & naming function decoration", "Celebrate your baby's naming ceremony with our specially designed decoration packages. Elegant cradle setups, floral arrangements, themed backdrops, and balloon accents create the perfect setting.", 2999, "/static/images/naming.svg"),
        ("corporate-events", "Corporate Event Decoration", "Professional event decor for office parties, launches & conferences", "Impress your team and clients with our corporate event decoration services. We handle office celebrations, product launches, annual days, and conference setups with professional elegance.", 4999, "/static/images/corporate.svg"),
        ("ring-ceremony", "Ring Ceremony Decoration", "Elegant engagement & ring ceremony decoration setups", "Make your engagement day memorable with our stunning ring ceremony decorations. Romantic backdrops, floral arrangements, and elegant stage setups tailored to your style.", 4999, "/static/images/ring.svg"),
        ("kids-party", "Kids Birthday Party", "Fun cartoon themes, character decorations & activity setups for kids", "Create magical moments for your little ones with our kids party decoration packages. Popular themes include Cocomelon, Paw Patrol, Frozen, Unicorn, Dinosaur, and more!", 2499, "/static/images/kids.svg"),
    ]

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

    for loc in localities:
        c.execute("INSERT OR IGNORE INTO localities (slug, name) VALUES (?, ?)", loc)

    # Seed testimonials
    testimonials = [
        ("Priya Sharma", "PartyBing did an amazing birthday decoration for my daughter's 5th birthday. The unicorn theme was perfect and the kids loved it! Very professional team.", 5, "Birthday Decoration"),
        ("Rahul Patil", "Booked them for our anniversary surprise. The romantic room setup with candles and roses was exactly what I wanted. Wife was thrilled!", 5, "Anniversary Decoration"),
        ("Sneha Joshi", "Used PartyBing for our baby shower. The pastel theme was gorgeous and they set up everything on time. Highly recommended in Pune!", 5, "Baby Shower Decoration"),
        ("Amit Kulkarni", "Corporate annual day decoration was handled superbly. Professional, punctual, and the stage looked amazing. Will use again.", 5, "Corporate Events"),
        ("Meera Deshmukh", "The haldi decoration was so vibrant and beautiful. All our guests complimented the setup. Thank you PartyBing team!", 5, "Haldi Decoration"),
        ("Vikram Singh", "Balloon arch for my son's birthday party was outstanding. Great quality balloons and very creative design. Value for money!", 4, "Balloon Decoration"),
    ]

    for t in testimonials:
        c.execute("INSERT OR IGNORE INTO testimonials (name, text, rating, service) VALUES (?, ?, ?, ?)", t)

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
