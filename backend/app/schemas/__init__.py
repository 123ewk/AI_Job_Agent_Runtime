"""Pydantic DTO（Data Transfer Object）。

DTO 与 ORM Model 解耦：API 层只暴露 DTO，禁止泄露 ORM 实例，
避免序列化未加载字段触发隐式 IO 与字段过度暴露。
"""
