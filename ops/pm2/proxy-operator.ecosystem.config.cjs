module.exports = {
  apps: [
    {
      name: 'proxy-operator',
      cwd: process.env.APP_CWD || '/srv/shupremium-stack/current/proxy-gateway/proxy-operator',
      script: 'src/server.js',
      watch: false,
      autorestart: true,
      max_memory_restart: '256M',
      env: {
        NODE_ENV: 'production',
      },
    },
  ],
};

