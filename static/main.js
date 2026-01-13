// Auto-show any flashed Bootstrap toasts
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.toast').forEach(t => new bootstrap.Toast(t).show());
});
