(function () {
  "use strict";

  var activeToggleHandler = null;
  var REPO_STATS_CACHE_KEY = "pm_github_repo_facts_v1";
  var REPO_STATS_TTL_MS = 5 * 60 * 1000; // 5 minutes

  function formatCompactCount(value) {
    if (typeof value !== "number" || !isFinite(value)) {
      return "0";
    }
    if (value >= 1000) {
      return (value / 1000).toFixed(1).replace(/\.0$/, "") + "k";
    }
    return String(value);
  }

  function clearStaleMaterialGitFacts() {
    try {
      for (var i = sessionStorage.length - 1; i >= 0; i--) {
        var key = sessionStorage.key(i);
        if (key && key.indexOf("__git-facts") !== -1) {
          sessionStorage.removeItem(key);
        }
      }
    } catch (_err) {
      // Ignore storage access errors in private browsing modes
    }
  }

  function renderRepoFacts(facts) {
    var repoContainers = document.querySelectorAll(".md-source__repository");
    for (var i = 0; i < repoContainers.length; i++) {
      var container = repoContainers[i];
      var existing = container.querySelector(".md-source__facts");
      if (existing) {
        existing.remove();
      }
      var list = document.createElement("ul");
      list.className = "md-source__facts";

      if (facts.version) {
        var liVer = document.createElement("li");
        liVer.className = "md-source__fact md-source__fact--version";
        liVer.textContent = facts.version;
        list.appendChild(liVer);
      }

      var liStars = document.createElement("li");
      liStars.className = "md-source__fact md-source__fact--stars";
      liStars.textContent = formatCompactCount(facts.stars);
      list.appendChild(liStars);

      var liForks = document.createElement("li");
      liForks.className = "md-source__fact md-source__fact--forks";
      liForks.textContent = formatCompactCount(facts.forks);
      list.appendChild(liForks);

      container.appendChild(list);
      container.classList.add("md-source__repository--active");
    }
  }

  function refreshLiveRepoFacts() {
    var cached = null;
    try {
      var raw = sessionStorage.getItem(REPO_STATS_CACHE_KEY);
      if (raw) {
        var parsed = JSON.parse(raw);
        if (parsed && Date.now() - parsed.ts < REPO_STATS_TTL_MS && parsed.data) {
          cached = parsed.data;
        }
      }
    } catch (_err) {
      cached = null;
    }

    if (cached) {
      renderRepoFacts(cached);
      return;
    }

    clearStaleMaterialGitFacts();

    var repoUrl = "https://api.github.com/repos/wkambale/pymomo";
    var releaseUrl = "https://api.github.com/repos/wkambale/pymomo/releases/latest";

    Promise.all([
      fetch(repoUrl, { cache: "no-store" }).then(function (r) {
        return r.ok ? r.json() : null;
      }),
      fetch(releaseUrl, { cache: "no-store" }).then(function (r) {
        return r.ok ? r.json() : null;
      }),
    ])
      .then(function (results) {
        var repo = results[0];
        var release = results[1];
        if (!repo && !release) {
          return;
        }
        var facts = {
          version: release && release.tag_name ? String(release.tag_name) : "",
          stars: repo && typeof repo.stargazers_count === "number" ? repo.stargazers_count : 0,
          forks: repo && typeof repo.forks_count === "number" ? repo.forks_count : 0,
        };
        try {
          sessionStorage.setItem(
            REPO_STATS_CACHE_KEY,
            JSON.stringify({ ts: Date.now(), data: facts })
          );
        } catch (_err) {
          // Ignore storage quota/privacy errors
        }
        renderRepoFacts(facts);
      })
      .catch(function () {
        // Keep Material's fallback UI silently if GitHub API is unreachable
      });
  }

  function ensureScrollTopButton() {
    var existing = document.getElementById("pm-scroll-top");
    var button = existing;

    if (!button) {
      button = document.createElement("button");
      button.id = "pm-scroll-top";
      button.type = "button";
      button.className = "pm-scroll-top";
      button.setAttribute("aria-label", "Go to top");
      button.innerHTML =
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg>';

      button.addEventListener("click", function () {
        var reducedMotion =
          window.matchMedia &&
          window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        window.scrollTo({
          top: 0,
          left: 0,
          behavior: reducedMotion ? "instant" : "smooth",
        });
      });

      document.body.appendChild(button);
    }

    if (activeToggleHandler) {
      window.removeEventListener("scroll", activeToggleHandler);
    }

    activeToggleHandler = function () {
      var btn = document.getElementById("pm-scroll-top");
      if (!btn) {
        return;
      }
      if (window.scrollY > 420) {
        btn.classList.add("is-visible");
      } else {
        btn.classList.remove("is-visible");
      }
    };

    window.addEventListener("scroll", activeToggleHandler, { passive: true });
    activeToggleHandler();
  }

  function resetScrollOnRouteChange() {
    if (!window.location.hash) {
      window.scrollTo({ top: 0, left: 0, behavior: "instant" });
    }
  }

  if (typeof document$ !== "undefined" && document$.subscribe) {
    document$.subscribe(function () {
      ensureScrollTopButton();
      resetScrollOnRouteChange();
      refreshLiveRepoFacts();
    });
  } else {
    document.addEventListener("DOMContentLoaded", function () {
      ensureScrollTopButton();
      refreshLiveRepoFacts();
    });
  }
})();
