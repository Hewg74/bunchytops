/* ============================================================
   THE BUNCHY TOPS — script.js
   island energy, east coast grit.
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {

  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // --- Intersection Observer: Scroll Reveals ---
  const revealObserver = new IntersectionObserver((entries, obs) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        obs.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });

  document.querySelectorAll('.reveal').forEach(el => revealObserver.observe(el));

  // --- Mobile Menu ---
  const hamburger = document.getElementById('hamburger');
  const mobileMenu = document.getElementById('mobile-menu');

  if (hamburger && mobileMenu) {
    const mobileLinks = mobileMenu.querySelectorAll('.nav__mobile-link');

    function toggleMenu() {
      const isOpen = hamburger.classList.toggle('is-active');
      mobileMenu.classList.toggle('is-open', isOpen);
      hamburger.setAttribute('aria-expanded', isOpen);
      mobileMenu.setAttribute('aria-hidden', !isOpen);
      document.body.style.overflow = isOpen ? 'hidden' : '';
    }

    hamburger.addEventListener('click', toggleMenu);
    mobileLinks.forEach(link => link.addEventListener('click', toggleMenu));
  }

  // --- Gallery: Horizontal Scroll via Mouse Wheel ---
  const galleryTrack = document.getElementById('gallery-track');

  if (galleryTrack) {
    galleryTrack.addEventListener('wheel', (e) => {
      if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
        const atStart = galleryTrack.scrollLeft === 0;
        const atEnd = galleryTrack.scrollLeft + galleryTrack.clientWidth >= galleryTrack.scrollWidth - 2;

        if ((e.deltaY < 0 && !atStart) || (e.deltaY > 0 && !atEnd)) {
          e.preventDefault();
          galleryTrack.scrollLeft += e.deltaY * 2;
        }
      }
    }, { passive: false });

    // Drag-to-scroll for gallery
    let isDragging = false;
    let startX = 0;
    let scrollStart = 0;

    galleryTrack.addEventListener('mousedown', (e) => {
      isDragging = true;
      startX = e.pageX;
      scrollStart = galleryTrack.scrollLeft;
      galleryTrack.style.cursor = 'grabbing';
    });

    window.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      e.preventDefault();
      galleryTrack.scrollLeft = scrollStart - (e.pageX - startX);
    });

    window.addEventListener('mouseup', () => {
      isDragging = false;
      galleryTrack.style.cursor = '';
    });
  }

  // --- Video Fallback: Show poster image if video fails ---
  document.querySelectorAll('video').forEach(video => {
    video.addEventListener('error', () => {
      video.style.display = 'none';
    }, true);

    // Also handle source errors
    video.querySelectorAll('source').forEach(source => {
      source.addEventListener('error', () => {
        video.style.display = 'none';
      });
    });
  });

  // --- Footer Year ---
  const yearEl = document.getElementById('footer-year');
  if (yearEl) yearEl.textContent = new Date().getFullYear();

});
