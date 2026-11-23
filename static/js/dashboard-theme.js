// Xiaozhi theme toggle. Lưu localStorage 'xiaozhi-theme'.
(() => {
  const root = document.documentElement;
  if (window.self !== window.top) root.dataset.embed = "1";
  const key = 'xiaozhi-theme';
  let choice;
  try { choice = localStorage.getItem(key); } catch { choice = null; }
  const preferred = () => choice === 'light' || choice === 'dark'
    ? choice : (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const apply = () => {
    const theme = preferred();
    root.dataset.theme = theme;
    root.style.colorScheme = theme;
    const btn = document.getElementById('theme-toggle');
    if (btn) {
      const next = theme === 'dark' ? 'sáng' : 'tối';
      btn.setAttribute('aria-label', `Chuyển sang giao diện ${next}`);
      btn.title = `Giao diện ${next}`;
    }
    document.querySelector('meta[name="theme-color"]')
      ?.setAttribute('content', theme === 'dark' ? '#0a0a0c' : '#f5f6f8');
  };
  apply();
  document.addEventListener('DOMContentLoaded', () => {
    apply();
    document.getElementById('theme-toggle')?.addEventListener('click', () => {
      choice = root.dataset.theme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem(key, choice); } catch {}
      apply();
    });
  });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (choice !== 'dark' && choice !== 'light') apply();
  });
  
  // [FIX 14] Đồng bộ theme khi thay đổi từ tab khác hoặc iframe
  window.addEventListener('storage', e => {
    if (e.key === key) {
      choice = e.newValue;
      apply();
    }
  });
})();