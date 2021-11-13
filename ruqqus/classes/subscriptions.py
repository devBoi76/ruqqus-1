from ruqqus.helpers.base36 import *
from ruqqus.helpers.security import *
from sqlalchemy import *
from sqlalchemy.orm import relationship
from ruqqus.__main__ import Base, cache
import time


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id"))
    board_id = Column(BigInteger, ForeignKey("boards.id"))
    created_utc = Column(BigInteger, default=0)
    is_active = Column(Boolean, default=True)
    get_notifs=Column(Boolean, default=False)

    user = relationship("User", uselist=False, back_populates="subscriptions")
    board = relationship("Board", uselist=False)

    def __init__(self, *args, **kwargs):
        if "created_utc" not in kwargs:
            kwargs["created_utc"] = int(time.time())

        super().__init__(*args, **kwargs)

    def __repr__(self):
        return f"<Subscription(id={self.id})>"


class Follow(Base):
    __tablename__ = "follows"
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id"))
    target_id = Column(BigInteger, ForeignKey("users.id"))
    created_utc = Column(BigInteger, default=0)
    get_notifs=Column(Boolean, default=False)

    user = relationship(
        "User",
        uselist=False,
        primaryjoin="User.id==Follow.user_id",
        back_populates="following")
    target = relationship(
        "User",
        lazy="joined",
        primaryjoin="User.id==Follow.target_id",
        back_populates="followers")

    def __init__(self, *args, **kwargs):
        if "created_utc" not in kwargs:
            kwargs["created_utc"] = int(time.time())

        super().__init__(*args, **kwargs)

    def __repr__(self):
        return f"<Follow(id={self.id})>"
