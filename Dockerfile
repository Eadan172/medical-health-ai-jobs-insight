# 自动化服务镜像：调度器 + HTTP 接口 + 已构建的前端
#
#   docker build -t jobsinsight .
#   docker run -p 8787:8787 -e JOBSINSIGHT_LLM_API_KEY=sk-xxx jobsinsight

FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-alpine
WORKDIR /app

# 运行时零依赖，只需要标准库；tzdata 用于 [schedule] 的时区。
RUN apk add --no-cache tzdata
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY automation/ /app/automation/
COPY --from=web /web/dist /app/web/dist
COPY web/public/data /app/web/public/data

# 容器里默认监听所有网卡，其余配置仍可用 JOBSINSIGHT_* 覆盖。
ENV JOBSINSIGHT_SERVER_HOST=0.0.0.0 \
    JOBSINSIGHT_SERVER_PORT=8787 \
    PYTHONPATH=/app/automation

EXPOSE 8787
VOLUME ["/app/automation/state", "/app/web/public/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s \
    CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['JOBSINSIGHT_SERVER_PORT']}/api/health\", timeout=3).status == 200 else 1)"

WORKDIR /app/automation
CMD ["python", "-m", "jobsinsight", "serve"]
