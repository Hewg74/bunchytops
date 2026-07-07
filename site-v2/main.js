// The Bunchy Tops - motion spine. GSAP + ScrollTrigger.
// Reduced-motion contract (kit): scroll scrub + drift off, entrances become instant.
(function () {
  "use strict";
  // .js class is set by an inline head script (before paint) so .js .reveal hides without FOUC
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // footer year
  var yr = document.getElementById("year");
  if (yr) yr.textContent = new Date().getFullYear();

  // nav gains a solid backing once scrolled off the hero (links stay legible over dark sections)
  var navEl = document.querySelector("nav");
  var hero = document.querySelector(".hero");
  if (navEl && hero && "IntersectionObserver" in window) {
    new IntersectionObserver(function (entries) {
      navEl.classList.toggle("scrolled", !entries[0].isIntersecting);
    }, { rootMargin: "-70px 0px 0px 0px" }).observe(hero);
  }

  // if GSAP failed to load, don't leave .reveal content stuck invisible
  // guard BOTH scripts: gsap without ScrollTrigger would throw on registerPlugin
  if (!window.gsap || typeof ScrollTrigger === "undefined") {
    document.querySelectorAll(".reveal, [data-anim]").forEach(function (el) {
      el.style.opacity = 1; el.style.transform = "none";
    });
    return;
  }

  if (reduce) {
    // no motion: everything visible on first paint
    gsap.set("[data-anim], .reveal", { opacity: 1, y: 0, clearProps: "transform" });
    document.querySelectorAll(".reveal").forEach(function (el) { el.classList.add("in"); });
    return;
  }

  gsap.registerPlugin(ScrollTrigger);
  var SWELL = "power2.out"; // matches --swell

  // hero: dub-echo entrance on load (translateY 28 -> 0, 800ms, staggered behind the beat)
  var heroItems = gsap.utils.toArray(".hero [data-anim]");
  gsap.set(heroItems, { y: 28, opacity: 0 });
  var tl = gsap.timeline({ delay: 0.25 });
  heroItems.forEach(function (el, i) {
    tl.to(el, { y: 0, opacity: 1, duration: 0.8, ease: SWELL }, i * 0.14);
  });

  // slow the footage 15% so the coast drone reads directed, not stock
  var v = document.querySelector(".hero-video");
  if (v) v.playbackRate = 0.85;

  // section reveals: fade-rise as each enters, light stagger for grouped items
  ScrollTrigger.batch(".reveal", {
    start: "top 85%",
    onEnter: function (batch) {
      gsap.to(batch, {
        y: 0, opacity: 1, duration: 0.8, ease: SWELL, stagger: 0.1,
        onStart: function () { batch.forEach(function (el) { el.classList.add("in"); }); }
      });
    },
    once: true
  });
})();
