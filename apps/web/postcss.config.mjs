// Конфигурация PostCSS для Tailwind CSS v4.
// В v4 плагин вынесен в отдельный пакет @tailwindcss/postcss, а основная
// настройка темы живёт в CSS (@theme), поэтому tailwind.config.js не нужен.
const config = {
  plugins: ["@tailwindcss/postcss"],
};

export default config;
