module.exports = {
  apps: [
    {
      name: 'portal',
      cwd: process.env.APP_CWD || '/srv/shupremium-stack/current/portal',
      script: 'main.py',
      interpreter: process.env.APP_PYTHON || '/srv/shupremium-stack/shared/portal/venv/bin/python',
      watch: false,
      autorestart: true,
      max_memory_restart: '512M',
      env: {
        APP_DEBUG: 'false',
      },
    },
  ],
};

