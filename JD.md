AI存储专家（Storage AI Expert）
工作职责
1. 负责分布式存储系统底层基础设施的设计、开发与性能优化，推动存储全栈、包括文件、对象、块存储以及分布式一致性层的技术发展
2. 参与调度系统、内存池化等基础机制的开发，提升系统整体性能与效率
3. 参与存储网络协议栈（如RDMA、TCP/UDP）的定制化开发与性能调优，以确保实现低延迟和高吞吐量的数据传输
4. 研究大模型在 GPU 服务器/AI PC/边缘设备等平台上的部署，性能瓶颈分析与调优。
5. 基于 vLLM、SGLang、llama.cpp、Ollama、KTransformers、TensorRT-LLM 等推理框架，分析模型推理过程中的计算、显存、内存与存储需求。
6. 研究存储相关的关键AI领域技术，包括 KV Cache 的生成、访问、复用、卸载和回读机制，及分层卸载方案，PD分离架构对存储需求，长上下文推理，及超高性能SSD等领域，推导产品核心需求，并于上下游合作制定产品架构和技术路线图。
7. 主导面向AI新产品架构方向的技术预研、需求定义，并驱动产业上游。
8. 跟踪 GPU Direct Storage、GPU Initiated Storage、CXL、NVMe、OCP等AI领域相关技术与标准演进,  评估对产品影响并提出相关标准提案和建议。。

任职资格
1. 熟悉 Linux 系统，具备良好的问题定位、性能分析和实验验证能力。
2. 熟悉 Python、C/C++、Shell 中至少一种编程语言，能够进行实验脚本开发、数据分析和原型验证
3. 精通异步编程模型（如Linux AIO、io_uring），并理解协程（Coroutine）实现的原理与应用
4. 深入理解存储栈原理，熟悉块设备驱动、页面缓存、I/O调度等机制
5. 系统能力：深入理解Linux内核、文件系统、I/O机制，具备多线程/高并发编程经验
6. 性能优化：对性能调优有强烈驱动力，能解决大规模集群下的延迟、吞吐瓶颈
7. 理解 Transformer、大模型推理流程、Attention、KV Cache、Prefill / Decode、上下文窗口、Batching 等基本概念。
8. 熟悉至少一种主流大模型推理框架的部署和使用调优，如 vLLM、SGLang、llama.cpp、TensorRT-LLM、Ollama、KTransformers 等。
9. 有开源大模型部署、量化、推理优化、长上下文调优经验者优先。
10. 熟悉 SSD、NAND Flash、NVMe、PCIe、Linux IO Stack、文件系统、块设备等基础知识者优先。
11. 熟悉 fio、SPDK、io_uring、libaio、GDS等系统性能工具或技术者优先。
12. 理解 IOPS、带宽、延迟、QoS、写放大、GC、FTL、SLC Cache、QLC 等 SSD 关键概念者优先。
13. 熟悉存储硬件特性（HDD/SSD/NVMe等），具备I/O性能分析与优化能力
14. 具备良好的技术表达能力，能够将前沿技术问题转化为清晰的架构观点、实验方案和产品建议。
15. 熟练使用主流 AI技术和工具，对基础设施、存储系统、硬件架构演进有强烈兴趣，愿意探索新领域.


加分项
1. 有分布式存储系统 Ceph 核心模块的开发经验。
2. 熟悉开源协程库（如libco、Boost.Coroutine）或自研协程框架的经验。
3. 具备kernel bypass（如DPDK、SPDK等）的实际应用经验
4. 跟踪行业前沿（如DPU硬件卸载、存算分离架构），推动技术落地