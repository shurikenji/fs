module.exports = {
  apps: [
    {
      name: 'platform-control',
      cwd: process.env.APP_CWD || '/srv/shupremium-stack/current/platform-control',
      script: 'main.py',
      interpreter: process.env.APP_PYTHON || '/srv/shupremium-stack/shared/platform-control/venv/bin/python',
      watch: false,
      autorestart: true,
      max_memory_restart: '512M',
      env: {
        APP_DEBUG: 'false',
      },
    },
  ],
};

