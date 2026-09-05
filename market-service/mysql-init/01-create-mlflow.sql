CREATE DATABASE IF NOT EXISTS fintrack_mlflow
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

GRANT ALL PRIVILEGES ON fintrack_mlflow.* TO 'fintrack'@'%';
FLUSH PRIVILEGES;
