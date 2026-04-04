// PM2 Ecosystem - Auto-generated 2026-03-25T11:46:14.075Z
// DO NOT EDIT MANUALLY - Managed by Admin Panel

module.exports = {
  apps: [
    {
        "name": "proxy-gpt1",
        "script": "./src/index.js",
        "instances": 2,
        "exec_mode": "cluster",
        "autorestart": true,
        "watch": false,
        "max_memory_restart": "512M",
        "env": {
            "NODE_ENV": "production",
            "PORT": 3001,
            "TARGET_HOST": "api.aabao.top",
            "SERVICE_NAME": "GPT1",
            "PROXY_DOMAIN": "gpt1.shupremium.com",
            "LOG_LEVEL": "warn"
        },
        "error_file": "./logs/gpt1-error.log",
        "out_file": "./logs/gpt1-out.log",
        "log_date_format": "YYYY-MM-DD HH:mm:ss",
        "merge_logs": true
    },
    {
        "name": "proxy-gpt2",
        "script": "./src/index.js",
        "instances": 2,
        "exec_mode": "cluster",
        "autorestart": true,
        "watch": false,
        "max_memory_restart": "512M",
        "env": {
            "NODE_ENV": "production",
            "PORT": 3002,
            "TARGET_HOST": "api.996444.cn",
            "SERVICE_NAME": "GPT2",
            "PROXY_DOMAIN": "gpt2.shupremium.com",
            "LOG_LEVEL": "warn"
        },
        "error_file": "./logs/gpt2-error.log",
        "out_file": "./logs/gpt2-out.log",
        "log_date_format": "YYYY-MM-DD HH:mm:ss",
        "merge_logs": true
    },
    {
        "name": "proxy-gpt3",
        "script": "./src/index.js",
        "instances": 2,
        "exec_mode": "cluster",
        "autorestart": true,
        "watch": false,
        "max_memory_restart": "512M",
        "env": {
            "NODE_ENV": "production",
            "PORT": 3003,
            "TARGET_HOST": "www.mnapi.com",
            "SERVICE_NAME": "gpt3",
            "PROXY_DOMAIN": "gpt3.shupremium.com",
            "LOG_LEVEL": "warn"
        },
        "error_file": "./logs/gpt3-error.log",
        "out_file": "./logs/gpt3-out.log",
        "log_date_format": "YYYY-MM-DD HH:mm:ss",
        "merge_logs": true
    },
    {
        "name": "proxy-gpt4",
        "script": "./src/index.js",
        "instances": 2,
        "exec_mode": "cluster",
        "autorestart": true,
        "watch": false,
        "max_memory_restart": "512M",
        "env": {
            "NODE_ENV": "production",
            "PORT": 3004,
            "TARGET_HOST": "api.kksj.org",
            "SERVICE_NAME": "GPT4",
            "PROXY_DOMAIN": "gpt4.shupremium.com",
            "LOG_LEVEL": "warn"
        },
        "error_file": "./logs/gpt4-error.log",
        "out_file": "./logs/gpt4-out.log",
        "log_date_format": "YYYY-MM-DD HH:mm:ss",
        "merge_logs": true
    },
    {
        "name": "proxy-gpt5",
        "script": "./src/index.js",
        "instances": 2,
        "exec_mode": "cluster",
        "autorestart": true,
        "watch": false,
        "max_memory_restart": "512M",
        "env": {
            "NODE_ENV": "production",
            "PORT": 3005,
            "TARGET_HOST": "new.xjai.cc",
            "SERVICE_NAME": "GPT5",
            "PROXY_DOMAIN": "gpt5.shupremium.com",
            "LOG_LEVEL": "warn"
        },
        "error_file": "./logs/gpt5-error.log",
        "out_file": "./logs/gpt5-out.log",
        "log_date_format": "YYYY-MM-DD HH:mm:ss",
        "merge_logs": true
    },
    {
        "name": "proxy-sv1",
        "script": "./src/index.js",
        "instances": 2,
        "exec_mode": "cluster",
        "autorestart": true,
        "watch": false,
        "max_memory_restart": "512M",
        "env": {
            "NODE_ENV": "production",
            "PORT": 4001,
            "TARGET_HOST": "api.zhongzhuan.chat",
            "SERVICE_NAME": "sv1",
            "PROXY_DOMAIN": "sv1.shupremium.com",
            "LOG_LEVEL": "warn"
        },
        "error_file": "./logs/sv1-error.log",
        "out_file": "./logs/sv1-out.log",
        "log_date_format": "YYYY-MM-DD HH:mm:ss",
        "merge_logs": true
    },
    {
        "name": "proxy-sv2",
        "script": "./src/index.js",
        "instances": 2,
        "exec_mode": "cluster",
        "autorestart": true,
        "watch": false,
        "max_memory_restart": "512M",
        "env": {
            "NODE_ENV": "production",
            "PORT": 4002,
            "TARGET_HOST": "kfcv50.link",
            "SERVICE_NAME": "sv2",
            "PROXY_DOMAIN": "sv2.shupremium.com",
            "LOG_LEVEL": "warn"
        },
        "error_file": "./logs/sv2-error.log",
        "out_file": "./logs/sv2-out.log",
        "log_date_format": "YYYY-MM-DD HH:mm:ss",
        "merge_logs": true
    }
]
};
