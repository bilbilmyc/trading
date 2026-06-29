"""
余额数据模型
"""

from datetime import datetime

from pydantic import BaseModel, Field


class Balance(BaseModel):
    """账户余额数据模型
    
    Attributes:
        currency: 币种
        total: 总金额
        available: 可用金额
        frozen: 冻结金额
        exchange: 交易所名称
        updated_at: 更新时间
    """

    currency: str = Field(..., min_length=1, description="币种")
    exchange: str = Field(..., min_length=1, description="交易所名称")
    total: float = Field(0.0, ge=0, description="总金额")
    available: float = Field(0.0, ge=0, description="可用金额")
    frozen: float = Field(0.0, ge=0, description="冻结金额")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")

    @property
    def locked(self) -> float:
        """锁定金额（总余额 - 可用余额）"""
        return self.total - self.available

    @property
    def utilization_rate(self) -> float:
        """资金利用率"""
        if self.total == 0:
            return 0.0
        return (self.total - self.available) / self.total * 100

    def update_balance(self, total: float, available: float, frozen: float = None):
        """更新余额信息"""
        self.total = total
        self.available = available
        if frozen is not None:
            self.frozen = frozen
        else:
            self.frozen = total - available
        self.updated_at = datetime.utcnow()
