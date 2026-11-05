"""知识服务与 Runtime 共用的执行上限和内部头名称；不引入业务或传输依赖。"""

MAX_RETRIEVAL_SECONDS = 360
KNOWLEDGE_REQUEST_ID_HEADER = "X-Knowledge-Request-Id"
KNOWLEDGE_DISPATCH_WAIT_HEADER = "X-Knowledge-Dispatch-Wait-Ms"
KNOWLEDGE_CONTINUATION_HEADER = "X-Knowledge-Principal-Continuation"
