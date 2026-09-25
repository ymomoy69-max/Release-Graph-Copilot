# Bitbucket database migration

## 1. Purpose

This runbook describes how prompt-backend moves storage between MYSQL and GIT.

## 2. Backup

Take a backup before any storage change.

## 3. Flag flips

### 3.2 GIT storage

rehydrate must run before flag flip to GIT

The rehydrate step loads rows into the git-backed store. Skipping it leaves readers on an empty store.

## 4. Rollback

Revert the flag to MYSQL and redeploy the previous build.
