import datetime

from fastapi.security import OAuth2PasswordRequestForm
from typing import Optional
from jose import JWTError, jwt
from starlette import status

from db_connection import get_user_by_name_db, add_user_db

from dependency import pwd_context, logger, oauth2_scheme, TokenData, User, Token, credentials_exception
from fastapi import APIRouter, Depends, HTTPException

auth_router = APIRouter()

# to get a string like this run: openssl rand -hex 32
SECRET_KEY = "22013516088ae490602230e8096e61b86762f60ba48a535f0f0e2af32e87decd"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60*16  # 16 Hour Expiration

# Permission Names
ADMIN_STRING = "admin"
RESEARCHER_STRING = "researcher"
INVESTIGATOR_STRING = "investigator"


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def authenticate_user(username: str, password: str):
    user = get_user_by_name_db(username)
    if not user:
        return False
    if not verify_password(password, user.password):
        return False
    return user


def create_access_token(data: dict, expires_delta: Optional[datetime.timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.datetime.utcnow() + expires_delta
    else:
        expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def is_logged_out(token: str = Depends(oauth2_scheme)):

    # TODO: Implement Logout Functionality

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return True
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    user = get_user_by_name_db(username=token_data.username)
    return user is None


def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    user = get_user_by_name_db(username=token_data.username)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(current_user=Depends(get_current_user)):
    logger.debug('Current User Disabled:' + str(current_user.disabled))
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def current_user_investigator(token: str = Depends(oauth2_scheme)):
    """
    Permission Checking Function to be used as a Dependency
    :param token: User authentication token
    :return: User has sufficient permissions
    """
    user = get_current_user(token)
    if (INVESTIGATOR_STRING or ADMIN_STRING) not in user.roles:
        raise credentials_exception

    return user


async def current_user_researcher(token: str = Depends(oauth2_scheme)):
    """
    Permission Checking Function to be used as a Dependency
    :param token: User authentication token
    :return: User has sufficient permissions
    """
    user = get_current_user(token)
    if (RESEARCHER_STRING or ADMIN_STRING) not in user.roles:
        raise credentials_exception

    return user


async def current_user_admin(token: str = Depends(oauth2_scheme)):
    """
    Permission Checking Function to be used as a Dependency
    :param token: User authentication token
    :return: User has sufficient permissions
    """
    user = get_current_user(token)
    if ADMIN_STRING not in user.roles:
        raise credentials_exception

    return user


# -------------------------------------------------------------------------------
#
#           User Authentication Endpoints
#
# -------------------------------------------------------------------------------

@auth_router.post('/add_role', dependencies=[Depends(current_user_admin)])
async def add_permission_to_user(username, new_role):
    if not get_user_by_name_db(username):
        return {'status': 'failure', 'detail': 'User does not exist. Unable to modify permissions.'}

    if new_role not in [INVESTIGATOR_STRING, RESEARCHER_STRING, ADMIN_STRING]:
        return {'status': 'failure', 'detail': 'Role specified does not exist. Unable to modify permissions.'}


@auth_router.post("/login", response_model=Token, dependencies=[Depends(is_logged_out)])
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@auth_router.post('/new/', dependencies=[Depends(is_logged_out)])
def create_account(username, password, email=None, full_name=None):
    return add_user_db(username, password, email, full_name)


@auth_router.get("/profile/")
async def get_current_user_profile(current_user: User = Depends(get_current_active_user)):
    """
    Export the data of the current user to the client
    :param current_user: Currently logged in user to have data exported
    :return: Cleaned user profile
    """
    user_export_data = current_user.dict(exclude={'password', 'id'})
    return user_export_data
