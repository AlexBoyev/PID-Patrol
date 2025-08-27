import uvicorn
from dashboards.web_dashboard import app


def main():
    uvicorn.run(app, host="127.0.0.1", port=80)


if __name__ == "__main__":
    main()
