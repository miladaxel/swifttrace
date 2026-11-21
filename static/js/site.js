(() => {
    const toggles = [...document.querySelectorAll('[data-dropdown]')];
    const closeMenus = (except) => toggles.forEach(button => {
        if (button === except) return;
        document.getElementById(button.dataset.dropdown).hidden = true;
        button.setAttribute('aria-expanded', 'false');
    });
    toggles.forEach(button => {
        const menu = document.getElementById(button.dataset.dropdown);
        button.addEventListener('click', () => {
            const open = menu.hidden;
            closeMenus(button);
            menu.hidden = !open;
            button.setAttribute('aria-expanded', String(open));
        });
        button.addEventListener('keydown', event => {
            if (event.key !== 'ArrowDown') return;
            event.preventDefault();
            closeMenus(button);
            menu.hidden = false;
            button.setAttribute('aria-expanded', 'true');
            menu.querySelector('a, button')?.focus();
        });
    });
    document.addEventListener('click', event => {
        if (!event.target.closest('.nav-dropdown')) closeMenus();
    });
    const mobileToggle = document.getElementById('mobile-menu-btn');
    const mobileMenu = document.getElementById('mobile-menu');
    mobileToggle?.addEventListener('click', () => {
        mobileMenu.hidden = !mobileMenu.hidden;
        mobileToggle.setAttribute('aria-expanded', String(!mobileMenu.hidden));
        closeMenus();
    });
    document.addEventListener('keydown', event => {
        if (event.key !== 'Escape') return;
        const active = toggles.find(button => button.getAttribute('aria-expanded') === 'true');
        closeMenus();
        if (!mobileMenu.hidden) {
            mobileMenu.hidden = true;
            mobileToggle.setAttribute('aria-expanded', 'false');
            mobileToggle.focus();
        } else active?.focus();
    });
    document.querySelectorAll('a[href]').forEach(link => {
        if (link.getAttribute('href') === location.pathname) link.setAttribute('aria-current', 'page');
    });
    const heroTabs = [...document.querySelectorAll('[role=tablist] [role=tab]')];
    heroTabs.forEach((tab, index) => {
        tab.addEventListener('keydown', event => {
            let next;
            if (event.key === 'ArrowRight') next = (index + 1) % heroTabs.length;
            if (event.key === 'ArrowLeft') next = (index - 1 + heroTabs.length) % heroTabs.length;
            if (event.key === 'Home') next = 0;
            if (event.key === 'End') next = heroTabs.length - 1;
            if (next === undefined) return;
            event.preventDefault();
            heroTabs[next].click();
            heroTabs[next].focus();
        });
    });
    window.matchMedia('(min-width: 992px)').addEventListener('change', event => {
        if (!event.matches) return;
        mobileMenu.hidden = true;
        mobileToggle.setAttribute('aria-expanded', 'false');
    });
    document.querySelectorAll('[data-help]').forEach(button => {
        button.addEventListener('click', () => {
            const open = document.getElementById(button.dataset.help).classList.toggle('is-open');
            button.setAttribute('aria-expanded', String(open));
        });
    });
})();
