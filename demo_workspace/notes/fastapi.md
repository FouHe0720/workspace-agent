# FastAPI：服务边界

FastAPI 通过类型声明与 Pydantic 校验 API 入参，用响应模型约束输出。业务逻辑放 service，持久化与外部服务放 adapter。

与 RAG 的关系：FastAPI 提供请求和错误边界，RAG 负责检索及证据生成。HTTP 端点本身不会保证答案有依据。

学习练习：设计一个 question 长度有上限的请求模型，对无命中、外部超时分别返回结构化错误。不要把异常堆栈或密钥放进响应。
