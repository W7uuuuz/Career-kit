"""MCP 客户端测试——通过 stdio 协议真实调用 MCP 服务器。

数据目录必须隔离到沙箱：本测试会 start_session/intake/finalize 写档案，
曾经直接写进用户真实 ~/.career-kit（回归教训）。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PYTHON_EXE = sys.executable


async def _run_mcp_server(data_dir: Path):
    """连接 MCP 服务器并测试所有工具（异步主体）。"""
    print("=" * 60)
    print("MCP 客户端测试")
    print("=" * 60)

    # 配置服务器启动参数：数据目录隔离到沙箱，绝不写真实 ~/.career-kit
    env = dict(os.environ)
    env["CAREER_KIT_DATA_DIR"] = str(data_dir)
    env["PYTHONIOENCODING"] = "utf-8"
    server_params = StdioServerParameters(
        command=PYTHON_EXE,
        args=["-m", "src.server"],
        cwd=str(Path(__file__).parent.parent),
        env=env,
    )

    print("\n[1] 启动 MCP 服务器...")
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # 初始化
            await session.initialize()
            print("[OK] 服务器连接成功")

            # 列出所有工具
            print("\n[2] 获取工具列表...")
            tools = await session.list_tools()
            print(f"[OK] 共 {len(tools.tools)} 个工具:")
            for tool in tools.tools:
                print(f"  - {tool.name}: {tool.description[:50]}...")

            # 测试 start_session
            print("\n[3] 测试 start_session...")
            result = await session.call_tool("start_session", {})
            msg = result.content[0].text
            assert "Career Kit" in msg
            print(f"[OK] 返回欢迎信息 ({len(msg)} 字符)")

            # 测试 parse_resume（用测试文件）
            print("\n[4] 测试 parse_resume...")
            resume_file = data_dir / "test_resume.txt"
            resume_file.parent.mkdir(parents=True, exist_ok=True)
            resume_file.write_text(
                "Zhang San\nFrontend Developer\n3 years React experience", encoding="utf-8"
            )
            tmp_path = str(resume_file)

            result = await session.call_tool("parse_resume", {"file_path": tmp_path})
            resume_text = result.content[0].text
            assert "Zhang San" in resume_text
            assert "intake" in resume_text
            print(f"[OK] 简历解析成功，返回 {len(resume_text)} 字符")

            # 测试 intake
            print("\n[5] 测试 intake...")
            result = await session.call_tool("intake", {
                "section": "who",
                "data": '{"name": "Zhang San", "status": "在职"}'
            })
            who_result = result.content[0].text
            assert "已记录" in who_result
            print(f"[OK] intake who: {who_result}")

            result = await session.call_tool("intake", {
                "section": "have",
                "data": '{"core_skills": [{"skill": "React", "evidence": "3年项目实战，用户已确认", "user_verified": true, "authorship": "ai_assisted", "control_level": 7}], "experience": "3年", "self_assessment": {"resume_trust": "medium", "notes": "React 为 AI 生成+人工验证迭代"}}'
            })
            have_result = result.content[0].text
            print(f"[OK] intake have: {have_result}")

            # 测试 finalize_profile
            print("\n[6] 测试 finalize_profile...")
            result = await session.call_tool("finalize_profile", {})
            final_result = result.content[0].text
            assert "档案已确认" in final_result
            print(f"[OK] {final_result}")

            # 测试 analyze_gaps（还是 stub）
            print("\n[7] 测试 analyze_gaps...")
            result = await session.call_tool("analyze_gaps", {})
            gaps_result = result.content[0].text
            print(f"[OK] analyze_gaps: {gaps_result}")

    print("\n" + "=" * 60)
    print("所有 MCP 客户端测试通过!")
    print("=" * 60)


def test_mcp_server(tmp_path):
    """同步入口：pytest 无需 asyncio 插件即可运行；数据目录隔离到沙箱。"""
    assert asyncio.run(_run_mcp_server(tmp_path / "data")) is None


if __name__ == "__main__":
    import tempfile

    asyncio.run(_run_mcp_server(Path(tempfile.mkdtemp(prefix="ck_mcp_client_"))))
