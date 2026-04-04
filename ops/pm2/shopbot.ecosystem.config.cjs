module.exports = {
  apps: [
    {
      name: 'shopbot',
      cwd: process.env.APP_CWD || '/srv/shupremium-stack/current/shopbot',
      script: '-m',
      args: 'bot.main',
      interpreter: process.env.APP_PYTHON || '/srv/shupremium-stack/shared/shopbot/venv/bin/python',
      watch: false,
      autorestart: true,
      max_memory_restart: '512M',
    },
  ],
};

