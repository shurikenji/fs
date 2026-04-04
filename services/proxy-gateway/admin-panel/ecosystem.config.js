module.exports = {
  apps: [{
    name: 'admin-panel',
    script: './src/server.js',
    instances: 1,
    autorestart: true,
    watch: false,
    max_memory_restart: '256M',
    env: {
      NODE_ENV: 'production',
      ADMIN_PORT: 8080
    }
  }]
};
