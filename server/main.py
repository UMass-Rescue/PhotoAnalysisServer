from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette import status
from starlette.responses import JSONResponse

from dependency import CredentialException
from routers.auth import auth_router
from routers.model import model_router

app = FastAPI()


app.include_router(
    auth_router,
    prefix="/auth",
    tags=["auth"],
    responses={404: {"detail": "Not found"}},
)

app.include_router(
    model_router,
    prefix="/model",
    tags=["models"],
    responses={404: {"detail": "Not found"}},
)


@app.exception_handler(CredentialException)
async def credential_exception_handler(request: Request, exc: CredentialException):
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={
            "status": 'failure',
            "detail": "Unable to validate credentials."
        },
        headers={"WWW-Authenticate": "Bearer"},
    )



# -------------------------------
# Web Server Configuration
# -------------------------------

# Must have CORSMiddleware to enable localhost client and server
origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:5057",
    "http://localhost:5000",
    "http://localhost:6379",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------
# Basic Routes
# -------------------------------


@app.get("/")
async def root():
    return {"message": "PhotoAnalysisServer Running!"}



