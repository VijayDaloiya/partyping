// Mobile menu toggle
const hamburger = document.getElementById('hamburger');
const nav = document.getElementById('mainNav');

hamburger?.addEventListener('click', () => {
    nav.classList.toggle('active');
    hamburger.classList.toggle('active');
});

// Mobile dropdown toggle
document.querySelectorAll('.dropdown-toggle').forEach(toggle => {
    toggle.addEventListener('click', (e) => {
        if (window.innerWidth <= 768) {
            e.preventDefault();
            toggle.parentElement.classList.toggle('active');
        }
    });
});

// FAQ toggle
document.querySelectorAll('.faq-question').forEach(q => {
    q.addEventListener('click', () => {
        q.parentElement.classList.toggle('active');
    });
});

// Inquiry form submit
document.querySelectorAll('.inquiry-form').forEach(form => {
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const btn = form.querySelector('button[type="submit"]');
        const originalText = btn.textContent;
        btn.textContent = 'Sending...';
        btn.disabled = true;

        try {
            const formData = new FormData(form);
            const res = await fetch('/inquiry', { method: 'POST', body: formData });
            const data = await res.json();
            if (data.status === 'success') {
                form.innerHTML = '<div style="text-align:center;padding:20px;"><h3 style="color:#25d366;">Thank You! 🎉</h3><p>We\'ll contact you within 30 minutes.</p></div>';
            }
        } catch (err) {
            btn.textContent = originalText;
            btn.disabled = false;
            alert('Something went wrong. Please try WhatsApp instead.');
        }
    });
});

// Scroll animations
const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add('animate');
        }
    });
}, { threshold: 0.1 });

document.querySelectorAll('.service-card, .testimonial-card, .gallery-item').forEach(el => {
    observer.observe(el);
});

// Close mobile menu on link click
document.querySelectorAll('.nav a:not(.dropdown-toggle)').forEach(link => {
    link.addEventListener('click', () => {
        nav.classList.remove('active');
    });
});
