import unittest

from scripts.humanness_score import check_paragraph_length_variance


class HumannessScoreTests(unittest.TestCase):
    def test_paragraph_variance_ignores_structural_modules_and_captions(self):
        text = """
这条芯片消息真正值得看的，不是参数表，而是它离真实 AI 推理链路还有多远。芯片、算力、软件栈和推理服务会一起决定模型调用成本。

:::callout info
说白了，芯片新闻先别只看参数表。坑在这里：它最终要落到推理成本、接口适配和真实业务延迟上。
:::

国内热点入口是「微博热搜 / 中国芯片又传来好消息」。这篇文章不复述热搜，而是回到国产 AI 芯片进入真实推理链路这个问题。

*图 1：芯片新闻要落到推理链路里看，重点是算力、软件栈和真实工作负载。*

| 判断项 | 应该看什么 |
| --- | --- |
| 算力 | 真实模型负载下的吞吐和延迟 |
| 软件栈 | 驱动、算子库、框架适配 |

用户感受到的不是芯片型号，而是回答速度、稳定性和价格。如果软件栈没有打通，AI 应用会在推理延迟、并发能力和成本上暴露问题；如果打通了，同样的模型服务才可能用更可控的预算跑起来。这里还牵涉监控、日志、驱动版本和模型适配，不能只看一张参数表。

等等。

这里不能只看“能不能跑”。还要看接口是不是稳定，日志能不能追，账单是不是还能解释清楚。
"""
        ok, detail = check_paragraph_length_variance(text)
        self.assertTrue(ok, detail)


if __name__ == "__main__":
    unittest.main()
