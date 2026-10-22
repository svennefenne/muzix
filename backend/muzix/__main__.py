import uvicorn

from . import env


def main():
    uvicorn.run("muzix.app:get_app", factory=True, host=env.HOST, port=env.PORT,
                proxy_headers=True, forwarded_allow_ips="*", log_level="info",
                reload=env.DEV)


if __name__ == "__main__":
    main()
