from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import threading
import os


class MongoDBConnection:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        """实现单例模式的关键方法"""
        with cls._lock:  # 确保线程安全
            if not cls._instance:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, db_name=None):
        """初始化数据库连接"""
        # 避免重复初始化
        if self._initialized:
            return

        self.db_name = db_name
        self.host = os.environ.get("MONGODB_HOST", '192.168.50.130')
        self.port = os.environ.get("MONGODB_PORT", 27017)
        self.username = os.environ.get('MONGODB_USER', 'admin')
        self.password = os.environ.get('MONGODB_PASSWD', '')
        self.client = None
        self.db = None

        try:
            # 构建连接 URI
            uri = f'mongodb://{self.host}:{self.port}/'
            if self.username and self.password:
                uri = f'mongodb://{self.username}:{self.password}@{self.host}:{self.port}/'
            print(uri)
            # 创建客户端连接
            self.client = MongoClient(uri)
            # 测试连接
            self.client.admin.command('ping')

            # 如果指定了数据库名称，获取数据库实例
            if self.db_name:
                self.db = self.client[self.db_name]
                print(f"已选择数据库: {self.db_name}")

            self._initialized = True
        except ConnectionFailure as e:
            print(f"连接失败: {e}")
            self.client = None
            self.db = None

    def get_client(self):
        """获取 MongoDB 客户端实例"""
        return self.client

    def get_database(self):
        """获取数据库实例"""
        return self.db

    def close(self):
        """关闭数据库连接"""
        if self.client:
            self.client.close()
            print("MongoDB 连接已关闭")
            self.client = None
            self.db = None


# 以下是数据库操作类，使用单例连接
class MongoDBManager:
    """MongoDB 操作管理类"""

    def __init__(self, db_name, collection_name):
        # 获取单例连接
        self.connection = MongoDBConnection(db_name=db_name)
        self.db = self.connection.get_database()
        self.collection = self.db[collection_name]

    def insert_data(self, data):
        """插入单条或多条数据"""
        try:
            if isinstance(data, list):
                result = self.collection.insert_many(data)
                print(f"成功插入 {len(result.inserted_ids)} 条数据")
                return result.inserted_ids
            else:
                result = self.collection.insert_one(data)
                print(f"成功插入数据，ID: {result.inserted_id}")
                return result.inserted_id
        except Exception as e:
            print(f"插入数据时发生错误: {e}")
            return None

    def query_data(self, query=None, projection=None):
        """查询数据"""

        try:
            if query is None:
                query = {}

            cursor = self.collection.find(query, projection)
            results = list(cursor)
            return results
        except Exception as e:
            print(f"查询数据时发生错误: {e}")
            return []

    def update_data(self, query, update, multi=False):
        """更新数据"""
        if not self.collection:
            print("未初始化集合")
            return None

        try:
            if multi:
                result = self.collection.update_many(query, update)
            else:
                result = self.collection.update_one(query, update)

            print(f"匹配 {result.matched_count} 条记录，更新 {result.modified_count} 条记录")
            return result
        except Exception as e:
            print(f"更新数据时发生错误: {e}")
            return None

    def delete_data(self, query, multi=False):
        """删除数据"""
        if not self.collection:
            print("未初始化集合")
            return None

        try:
            if multi:
                result = self.collection.delete_many(query)
            else:
                result = self.collection.delete_one(query)

            print(f"成功删除 {result.deleted_count} 条记录")
            return result
        except Exception as e:
            print(f"删除数据时发生错误: {e}")
            return None


class MCPSettingsManager:
    db_name = 'ai_agent'
    collection_name = 'user_mcp_settings'

    @classmethod
    def get_by_condition(cls, _id=None, uid=None, server=None) -> list:
        manager = MongoDBManager(db_name=cls.db_name, collection_name=cls.collection_name)
        query = {}
        if _id:
            query['_id'] = _id
        if uid:
            query['uid'] = uid
        if server:
            query['server'] = server
        if not query:
            return []
        settings = manager.query_data(query=query)
        return settings

    @classmethod
    def list_by_ids(cls, ids: list[str]) -> list:
        manager = MongoDBManager(db_name=cls.db_name, collection_name=cls.collection_name)
        query = {}
        if ids:
            query['_id'] = {'$in': ids}

        if not query:
            return []

        settings = manager.query_data(query=query)
        return settings

    @classmethod
    def list_by_system(cls) -> list:
        manager = MongoDBManager(db_name=cls.db_name, collection_name=cls.collection_name)
        query = {'server_type': 'system'}

        settings = manager.query_data(query=query)
        return settings

    @classmethod
    def to_mcp_config(cls, settings) -> dict:

        return {'mcpServers': {setting['name']: setting for setting in settings}}


# 使用示例
if __name__ == "__main__":
    mm = MongoDBManager(db_name='ai_agent', collection_name='user_mcp_settings')
    import uuid

    sample_data = [
        {
            '_id': uuid.uuid4().hex,
            'uid': 30786304,
            'name': 'math',
            'server_description': '计算两个数相加',
            "transport": 'sse',
            "url": os.environ.get("MCP_SSE_URL", ""),
            "tools": [
                {
                    "name": "addition_calculator",
                    "args": {
                        "a": {
                            "title": "A",
                            "type": "integer"
                        },
                        "b": {
                            "title": "B",
                            "type": "integer"
                        }
                    },
                    "description": "计算两个数的和",
                    "scenes": [
                        {
                            "name": "计算两个数的和",
                            "step": 1
                        }
                    ]
                }
            ],
            'created_ts': '2025-01-01 00:00:00',
            'updated_ts': '2025-01-01 00:00:00',
        }
    ]
    mm.insert_data(sample_data)
    print(mm.query_data())
    mm.connection.close()
