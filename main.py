from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.gzip import GZipMiddleware
from database import init_db, get_db, get_all_settings, get_setting, _unique_gallery_code
import os, json, shutil, uuid
from typing import Optional, List
from datetime import datetime
from functools import lru_cache
from PIL import Image
import time

app = FastAPI()
app.add_middleware(GZipMiddleware, minimum_size=500)

# Static files with cache headers
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
templates = Jinja2Templates(directory="templates")

# Create uploads dir
os.makedirs("uploads", exist_ok=True)

init_db()

# Simple in-memory cache
_cache = {}
CACHE_TTL = 300  # 5 minutes

def cached_context():
    now = time.time()
    if "_ctx" in _cache and now - _cache["_ctx_time"] < CACHE_TTL:
        return _cache["_ctx"]
    ctx = _common_context_fresh()
    _cache["_ctx"] = ctx
    _cache["_ctx_time"] = now
    return ctx

def invalidate_cache():
    _cache.clear()

def _common_context_fresh():
    settings = get_all_settings()
    conn = get_db()
    services = conn.execute("SELECT * FROM services WHERE is_active=1 ORDER BY display_order, id").fetchall()
    conn.close()
    return {"settings": settings, "services": [dict(s) for s in services], "year": datetime.now().year}

def optimize_image(filepath, max_width=1200, quality=80):
    """Compress and resize uploaded images."""
    try:
        img = Image.open(filepath)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        if img.width > max_width:
            ratio = max_width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((max_width, new_height), Image.LANCZOS)
        webp_path = filepath.rsplit('.', 1)[0] + '.webp'
        img.save(webp_path, 'WEBP', quality=quality)
        img.save(filepath, quality=quality)
        return webp_path
    except Exception:
        return filepath

def _safe_int_field(value, fallback):
    try:
        text = value.strip()
        return int(text) if text else fallback
    except (AttributeError, ValueError):
        return fallback

def _save_uploaded_image(upload: UploadFile):
    ext = os.path.splitext(upload.filename or "")[1].lower() or ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join("uploads", filename)
    with open(filepath, "wb") as f:
        shutil.copyfileobj(upload.file, f)
    optimize_image(filepath)
    return f"/uploads/{filename}", filepath

def _remove_uploaded_image(image_path: Optional[str]):
    if not image_path or not image_path.startswith("/uploads/"):
        return
    physical = image_path.lstrip("/")
    if os.path.exists(physical):
        os.remove(physical)
    webp_path = physical.rsplit(".", 1)[0] + ".webp"
    if os.path.exists(webp_path):
        os.remove(webp_path)


def common_context():
    return cached_context()


# ==================== PUBLIC ROUTES ====================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    conn = get_db()
    services = conn.execute("SELECT * FROM services WHERE is_active=1 ORDER BY display_order, id").fetchall()
    testimonials = conn.execute("SELECT * FROM testimonials WHERE is_active=1 ORDER BY id DESC LIMIT 6").fetchall()
    gallery = conn.execute("SELECT * FROM gallery ORDER BY display_order, id DESC LIMIT 8").fetchall()
    conn.close()
    ctx = common_context()
    return templates.TemplateResponse(request, "home.html", context={
        **ctx,
        "testimonials": testimonials, "gallery": gallery,
        "meta_title": "PartyBing - Best Party & Balloon Decoration in Pune | Starting ₹2499",
        "meta_description": "Pune's #1 party decoration service. Birthday, wedding, anniversary, baby shower & balloon decoration starting ₹2499. Book now on WhatsApp!",
    })


@app.get("/services/{slug}", response_class=HTMLResponse)
async def service_page(request: Request, slug: str):
    conn = get_db()
    service = conn.execute("SELECT * FROM services WHERE slug=? AND is_active=1", (slug,)).fetchone()
    if not service:
        conn.close()
        raise HTTPException(status_code=404)
    gallery = conn.execute("SELECT * FROM gallery WHERE service_id=? ORDER BY display_order", (service["id"],)).fetchall()
    # FAQ from JSON
    faq = json.loads(service["faq"]) if service["faq"] else []
    conn.close()
    ctx = common_context()
    meta_title = service["meta_title"] or f"{service['name']} in Pune Starting ₹{service['price']} | PartyBing"
    meta_desc = service["meta_description"] or f"Professional {service['name'].lower()} in Pune. Premium setups starting ₹{service['price']}. Doorstep service across all Pune areas. Book on WhatsApp!"
    return templates.TemplateResponse(request, "service.html", context={
        **ctx,
        "service": service, "gallery": gallery, "faq": faq,
        "meta_title": meta_title, "meta_description": meta_desc,
    })


@app.get("/area/{slug}", response_class=HTMLResponse)
async def locality_page(request: Request, slug: str):
    conn = get_db()
    locality = conn.execute("SELECT * FROM localities WHERE slug=? AND is_active=1", (slug,)).fetchone()
    if not locality:
        conn.close()
        raise HTTPException(status_code=404)
    services = conn.execute("SELECT * FROM services WHERE is_active=1 ORDER BY display_order, id").fetchall()
    conn.close()
    ctx = common_context()
    meta_title = locality["meta_title"] or f"Party & Balloon Decoration in {locality['name']}, Pune | PartyBing"
    meta_desc = locality["meta_description"] or f"Best decoration services in {locality['name']}, Pune. Birthday, balloon, wedding & event decoration starting ₹2499. Fast doorstep setup!"
    return templates.TemplateResponse(request, "locality.html", context={
        **ctx,
        "locality": locality,
        "meta_title": meta_title, "meta_description": meta_desc,
    })


@app.get("/gallery", response_class=HTMLResponse)
async def gallery_page(request: Request):
    conn = get_db()
    gallery = conn.execute("""
        SELECT g.*, s.name as service_name,
            (SELECT COUNT(*) FROM gallery_images gi WHERE gi.gallery_id=g.id) as extra_images
        FROM gallery g
        LEFT JOIN services s ON g.service_id=s.id
        ORDER BY g.display_order, g.id DESC
    """).fetchall()
    conn.close()
    ctx = common_context()
    return templates.TemplateResponse(request, "gallery.html", context={
        **ctx, "gallery": gallery,
        "meta_title": "Our Work Gallery | PartyBing Pune Decoration",
        "meta_description": "See our latest decoration work - birthday parties, balloon arches, wedding setups, baby showers and more in Pune.",
    })

@app.get("/gallery/{code}", response_class=HTMLResponse)
async def gallery_detail(request: Request, code: str):
    conn = get_db()
    item = conn.execute("""
        SELECT g.*, s.name as service_name
        FROM gallery g
        LEFT JOIN services s ON g.service_id=s.id
        WHERE g.code=?
    """, (code,)).fetchone()
    if not item:
        conn.close()
        raise HTTPException(status_code=404)
    images = conn.execute(
        "SELECT * FROM gallery_images WHERE gallery_id=? ORDER BY display_order, id",
        (item["id"],)
    ).fetchall()
    conn.close()
    ctx = common_context()
    return templates.TemplateResponse(request, "gallery_detail.html", context={
        **ctx,
        "item": item,
        "images": images,
        "meta_title": item["caption"] or f"{item['service_name'] or 'Gallery'} | PartyBing",
        "meta_description": item["caption"] or "PartyBing gallery item",
    })


@app.get("/contact", response_class=HTMLResponse)
async def contact_page(request: Request):
    ctx = common_context()
    return templates.TemplateResponse(request, "contact.html", context={
        **ctx,
        "meta_title": "Contact PartyBing | Book Decoration in Pune",
        "meta_description": "Book your party decoration in Pune. Call or WhatsApp us for instant quotes. Doorstep service across all Pune areas.",
    })


@app.get("/blog", response_class=HTMLResponse)
async def blog_list(request: Request):
    conn = get_db()
    posts = conn.execute("SELECT * FROM blog_posts WHERE is_published=1 ORDER BY created_at DESC").fetchall()
    conn.close()
    ctx = common_context()
    return templates.TemplateResponse(request, "blog_list.html", context={
        **ctx, "posts": posts,
        "meta_title": "Party Decoration Blog — Tips, Ideas & Price Guides | PartyBing Pune",
        "meta_description": "Read our latest articles on party decoration ideas, pricing guides, and tips for celebrations in Pune. Expert advice from PartyBing.",
    })


@app.get("/blog/{slug}", response_class=HTMLResponse)
async def blog_post(request: Request, slug: str):
    conn = get_db()
    post = conn.execute("SELECT * FROM blog_posts WHERE slug=? AND is_published=1", (slug,)).fetchone()
    if not post:
        conn.close()
        raise HTTPException(status_code=404)
    conn.close()
    ctx = common_context()
    meta_title = post["meta_title"] or post["title"]
    meta_desc = post["meta_description"] or post["excerpt"]
    return templates.TemplateResponse(request, "blog_post.html", context={
        **ctx, "post": post,
        "meta_title": meta_title, "meta_description": meta_desc,
    })


@app.post("/inquiry")
async def submit_inquiry(
    name: str = Form(...), phone: str = Form(...),
    service: str = Form(""), event_date: str = Form(""),
    locality: str = Form(""), message: str = Form("")
):
    conn = get_db()
    conn.execute(
        "INSERT INTO inquiries (name, phone, service, event_date, locality, message) VALUES (?,?,?,?,?,?)",
        (name, phone, service, event_date, locality, message)
    )
    conn.commit()
    conn.close()
    return JSONResponse({"status": "success", "message": "Thank you! We'll contact you shortly."})


@app.get("/sitemap.xml")
async def sitemap(request: Request):
    conn = get_db()
    services = conn.execute("SELECT slug FROM services WHERE is_active=1").fetchall()
    localities = conn.execute("SELECT slug FROM localities WHERE is_active=1").fetchall()
    blog_posts = conn.execute("SELECT slug FROM blog_posts WHERE is_published=1").fetchall()
    gallery_items = conn.execute("SELECT code FROM gallery WHERE code IS NOT NULL AND code != ''").fetchall()
    conn.close()
    base = "https://partybing.in"
    urls = [base + "/", base + "/gallery", base + "/contact", base + "/blog"]
    urls += [f"{base}/services/{s['slug']}" for s in services]
    urls += [f"{base}/area/{l['slug']}" for l in localities]
    urls += [f"{base}/blog/{p['slug']}" for p in blog_posts]
    urls += [f"{base}/gallery/{g['code']}" for g in gallery_items]

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for url in urls:
        xml += f"  <url><loc>{url}</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>\n"
    xml += "</urlset>"
    return HTMLResponse(content=xml, media_type="application/xml")


@app.get("/robots.txt")
async def robots():
    content = "User-agent: *\nAllow: /\nSitemap: https://partybing.in/sitemap.xml\n"
    return HTMLResponse(content=content, media_type="text/plain")


# ==================== ADMIN ROUTES ====================

def verify_admin(request: Request):
    token = request.cookies.get("admin_token")
    if token != get_setting("admin_password"):
        raise HTTPException(status_code=401)

@app.get("/admin", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    token = request.cookies.get("admin_token")
    if token == get_setting("admin_password"):
        return RedirectResponse("/admin/dashboard", status_code=302)
    return templates.TemplateResponse(request, "admin/login.html")

@app.post("/admin/login")
async def admin_login(password: str = Form(...)):
    if password == get_setting("admin_password"):
        response = RedirectResponse("/admin/dashboard", status_code=302)
        response.set_cookie("admin_token", password, httponly=True)
        return response
    return RedirectResponse("/admin?error=1", status_code=302)

@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    verify_admin(request)
    conn = get_db()
    stats = {
        "total_inquiries": conn.execute("SELECT COUNT(*) FROM inquiries").fetchone()[0],
        "new_inquiries": conn.execute("SELECT COUNT(*) FROM inquiries WHERE status='new'").fetchone()[0],
        "services": conn.execute("SELECT COUNT(*) FROM services WHERE is_active=1").fetchone()[0],
        "gallery": conn.execute("SELECT COUNT(*) FROM gallery").fetchone()[0],
    }
    inquiries = conn.execute("SELECT * FROM inquiries ORDER BY id DESC LIMIT 20").fetchall()
    conn.close()
    return templates.TemplateResponse(request, "admin/dashboard.html", context={
        "stats": stats, "inquiries": inquiries
    })

@app.get("/admin/services", response_class=HTMLResponse)
async def admin_services(request: Request):
    verify_admin(request)
    conn = get_db()
    services = conn.execute("SELECT * FROM services ORDER BY display_order, id").fetchall()
    conn.close()
    return templates.TemplateResponse(request, "admin/services.html", context={"services": services})

@app.post("/admin/services/{service_id}/update")
async def admin_update_service(request: Request, service_id: int):
    verify_admin(request)
    form = await request.form()
    conn = get_db()
    conn.execute("""UPDATE services SET name=?, short_desc=?, description=?, price=?,
        meta_title=?, meta_description=?, faq=?, is_active=?, display_order=? WHERE id=?""",
        (form["name"], form["short_desc"], form["description"], int(form["price"]),
         form.get("meta_title", ""), form.get("meta_description", ""), form.get("faq", ""),
         1 if form.get("is_active") else 0, int(form.get("display_order", 0)), service_id))
    conn.commit()
    conn.close()
    invalidate_cache()
    return RedirectResponse("/admin/services", status_code=302)

@app.get("/admin/gallery", response_class=HTMLResponse)
async def admin_gallery(request: Request):
    verify_admin(request)
    conn = get_db()
    gallery = conn.execute("""
        SELECT g.*, s.name as service_name,
            (SELECT COUNT(*) FROM gallery_images gi WHERE gi.gallery_id=g.id) as extra_images
        FROM gallery g
        LEFT JOIN services s ON g.service_id=s.id
        ORDER BY g.id DESC
    """).fetchall()
    services = conn.execute("SELECT id, name FROM services ORDER BY name").fetchall()
    conn.close()
    return templates.TemplateResponse(request, "admin/gallery.html", context={"gallery": gallery, "services": services})

@app.post("/admin/gallery/upload")
async def admin_upload_image(
    request: Request,
    thumbnail_image: UploadFile = File(...),
    extra_images: List[UploadFile] = File([]),
    caption: str = Form(""),
    service_id: int = Form(0),
    price: str = Form(""),
    discount_price: str = Form(""),
    code: str = Form("")
):
    verify_admin(request)
    default_price = int(get_setting("default_price") or 2499)
    final_price = _safe_int_field(price, default_price)
    final_discount_price = _safe_int_field(discount_price, final_price)
    if final_discount_price <= 0 or final_discount_price > final_price:
        final_discount_price = final_price
    conn = get_db()
    final_code = _unique_gallery_code(conn.cursor(), code)
    thumbnail_path, _ = _save_uploaded_image(thumbnail_image)
    conn.execute(
        "INSERT INTO gallery (image, caption, service_id, price, discount_price, code) VALUES (?,?,?,?,?,?)",
        (thumbnail_path, caption, service_id if service_id else None, final_price, final_discount_price, final_code)
    )
    gallery_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for order, extra_image in enumerate([image for image in extra_images if getattr(image, "filename", "")], start=1):
        extra_path, _ = _save_uploaded_image(extra_image)
        conn.execute(
            "INSERT INTO gallery_images (gallery_id, image, display_order) VALUES (?,?,?)",
            (gallery_id, extra_path, order)
        )
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/gallery", status_code=302)

@app.get("/admin/gallery/{item_id}", response_class=HTMLResponse)
async def admin_gallery_item(request: Request, item_id: int):
    verify_admin(request)
    conn = get_db()
    item = conn.execute("""
        SELECT g.*, s.name as service_name
        FROM gallery g
        LEFT JOIN services s ON g.service_id=s.id
        WHERE g.id=?
    """, (item_id,)).fetchone()
    if not item:
        conn.close()
        raise HTTPException(status_code=404)
    images = conn.execute(
        "SELECT * FROM gallery_images WHERE gallery_id=? ORDER BY display_order, id",
        (item_id,)
    ).fetchall()
    services = conn.execute("SELECT id, name FROM services ORDER BY name").fetchall()
    conn.close()
    return templates.TemplateResponse(request, "admin/gallery_item.html", context={
        "item": item,
        "images": images,
        "services": services,
    })

@app.post("/admin/gallery/{item_id}/update")
async def admin_update_gallery_item(
    request: Request,
    item_id: int,
    thumbnail_image: Optional[UploadFile] = File(None),
):
    verify_admin(request)
    form = await request.form()
    conn = get_db()
    item = conn.execute("SELECT * FROM gallery WHERE id=?", (item_id,)).fetchone()
    if not item:
        conn.close()
        raise HTTPException(status_code=404)
    new_code = _unique_gallery_code(conn.cursor(), form.get("code"), item_id=item_id)
    image_path = item["image"]
    if thumbnail_image and getattr(thumbnail_image, "filename", ""):
        _remove_uploaded_image(item["image"])
        image_path, _ = _save_uploaded_image(thumbnail_image)
    conn.execute("""
        UPDATE gallery
        SET image=?, caption=?, service_id=?, price=?, discount_price=?, code=?
        WHERE id=?
    """, (
        image_path,
        form.get("caption", ""),
        int(form.get("service_id", 0)) or None,
        _safe_int_field(form.get("price", ""), int(get_setting("default_price") or 2499)),
        _safe_int_field(form.get("discount_price", ""), _safe_int_field(form.get("price", ""), int(get_setting("default_price") or 2499))),
        new_code,
        item_id
    ))
    conn.commit()
    conn.close()
    return RedirectResponse(f"/admin/gallery/{item_id}", status_code=302)

@app.post("/admin/gallery/{item_id}/images/add")
async def admin_add_gallery_images(request: Request, item_id: int, images: List[UploadFile] = File([])):
    verify_admin(request)
    conn = get_db()
    item = conn.execute("SELECT id FROM gallery WHERE id=?", (item_id,)).fetchone()
    if not item:
        conn.close()
        raise HTTPException(status_code=404)
    current_max = conn.execute(
        "SELECT COALESCE(MAX(display_order), 0) FROM gallery_images WHERE gallery_id=?",
        (item_id,)
    ).fetchone()[0]
    order = current_max + 1
    for upload in images:
        if getattr(upload, "filename", ""):
            image_path, _ = _save_uploaded_image(upload)
            conn.execute(
                "INSERT INTO gallery_images (gallery_id, image, display_order) VALUES (?,?,?)",
                (item_id, image_path, order)
            )
            order += 1
    conn.commit()
    conn.close()
    return RedirectResponse(f"/admin/gallery/{item_id}", status_code=302)

@app.post("/admin/gallery/images/{image_id}/delete")
async def admin_delete_gallery_image(request: Request, image_id: int):
    verify_admin(request)
    conn = get_db()
    row = conn.execute("SELECT * FROM gallery_images WHERE id=?", (image_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404)
    _remove_uploaded_image(row["image"])
    conn.execute("DELETE FROM gallery_images WHERE id=?", (image_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(request.headers.get("referer", "/admin/gallery"), status_code=302)

@app.post("/admin/gallery/{item_id}/delete")
async def admin_delete_gallery(request: Request, item_id: int):
    verify_admin(request)
    conn = get_db()
    row = conn.execute("SELECT * FROM gallery WHERE id=?", (item_id,)).fetchone()
    child_rows = conn.execute("SELECT * FROM gallery_images WHERE gallery_id=? ORDER BY id", (item_id,)).fetchall()
    if row:
        _remove_uploaded_image(row["image"])
    for child in child_rows:
        _remove_uploaded_image(child["image"])
    conn.execute("DELETE FROM gallery WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/gallery", status_code=302)

@app.get("/admin/blog", response_class=HTMLResponse)
async def admin_blog(request: Request):
    verify_admin(request)
    conn = get_db()
    posts = conn.execute("SELECT * FROM blog_posts ORDER BY created_at DESC").fetchall()
    conn.close()
    return templates.TemplateResponse(request, "admin/blog.html", context={"posts": posts})

@app.post("/admin/blog/{post_id}/update")
async def admin_update_blog(request: Request, post_id: int):
    verify_admin(request)
    form = await request.form()
    conn = get_db()
    conn.execute("""UPDATE blog_posts SET title=?, slug=?, meta_title=?, meta_description=?,
        excerpt=?, content=?, tags=?, is_published=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
        (form["title"], form["slug"], form.get("meta_title", ""), form.get("meta_description", ""),
         form.get("excerpt", ""), form.get("content", ""), form.get("tags", ""),
         1 if form.get("is_published") else 0, post_id))
    conn.commit()
    conn.close()
    invalidate_cache()
    return RedirectResponse("/admin/blog", status_code=302)

@app.get("/admin/testimonials", response_class=HTMLResponse)
async def admin_testimonials(request: Request):
    verify_admin(request)
    conn = get_db()
    testimonials = conn.execute("SELECT * FROM testimonials ORDER BY id DESC").fetchall()
    conn.close()
    return templates.TemplateResponse(request, "admin/testimonials.html", context={"testimonials": testimonials})

@app.post("/admin/testimonials/add")
async def admin_add_testimonial(request: Request, name: str = Form(...), text: str = Form(...), rating: int = Form(5), service: str = Form("")):
    verify_admin(request)
    conn = get_db()
    conn.execute("INSERT INTO testimonials (name, text, rating, service) VALUES (?,?,?,?)", (name, text, rating, service))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/testimonials", status_code=302)

@app.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings(request: Request):
    verify_admin(request)
    settings = get_all_settings()
    return templates.TemplateResponse(request, "admin/settings.html", context={"settings": settings})

@app.post("/admin/settings")
async def admin_update_settings(request: Request):
    verify_admin(request)
    form = await request.form()
    conn = get_db()
    for key in form:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, form[key]))
    conn.commit()
    conn.close()
    invalidate_cache()
    return RedirectResponse("/admin/settings", status_code=302)

@app.post("/admin/inquiries/{inquiry_id}/status")
async def admin_update_inquiry(request: Request, inquiry_id: int, status: str = Form(...)):
    verify_admin(request)
    conn = get_db()
    conn.execute("UPDATE inquiries SET status=? WHERE id=?", (status, inquiry_id))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=302)

@app.get("/admin/logout")
async def admin_logout():
    response = RedirectResponse("/admin", status_code=302)
    response.delete_cookie("admin_token")
    return response
