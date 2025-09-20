#!/bin/bash

echo "Creating directories..."
mkdir -p backups
mkdir -p logs/bot/live
mkdir -p logs/bot/paper
mkdir -p logs/web
mkdir -p tbot_api
mkdir -p tbot_bot
mkdir -p tbot_web/assets/fnt
mkdir -p tbot_web/assets/css
mkdir -p scripts
mkdir -p docs
mkdir -p tbot_bot/enhancements
mkdir -p tbot_bot/backtest
mkdir -p tbot_bot/tests

echo "Creating placeholder files..."
touch gnu_live.gnucash
touch gnu_paper.gnucash
mkdir -p "$ROOT_DIR/tbot_bot/storage/secrets"
 touch "$ROOT_DIR/tbot_bot/storage/secrets/.env_bot.enc"

echo "Done. Please populate .env and .env_bot before first use."
