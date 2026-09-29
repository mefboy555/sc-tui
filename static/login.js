const form = document.getElementById('authform');
const err = document.getElementById('err');
const submitBtn = document.getElementById('submit');
let mode = 'login';

document.querySelectorAll('.tabs button').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('.tabs button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    mode = btn.dataset.mode;
    submitBtn.textContent = mode === 'login' ? 'Войти' : 'Зарегистрироваться';
    err.textContent = '';
  };
});

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const data = new FormData(form);
  err.textContent = '';
  try {
    const r = await fetch(`/api/${mode}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: data.get('username'),
        password: data.get('password'),
      }),
    });
    if (!r.ok) {
      const resp = await r.json().catch(() => ({}));
      err.textContent = resp.detail || 'Ошибка';
      return;
    }
    location.replace('/');
  } catch {
    err.textContent = 'Ошибка сети';
  }
});
