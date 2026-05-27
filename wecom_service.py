"""
企业微信 API 集成服务
- 消息加解密（AES-256-CBC + SHA1 签名）
- URL验证（echostr）
- XML 消息解析与构建

企业微信回调消息格式参考：
https://developer.work.weixin.qq.com/document/path/90238
"""
import base64
import hashlib
import json
import os
import random
import socket
import string
import struct
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from Crypto.Cipher import AES
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


class WXBizMsgCrypt:
    """企业微信消息加解密类

    实现企业微信回调消息的：
    1. URL验证（VerifyURL）
    2. 消息解密（DecryptMsg）
    3. 消息加密（EncryptMsg）
    """

    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        self.token = token
        self.corp_id = corp_id
        self.aes_key = base64.b64decode(encoding_aes_key + "=")

    def _sha1(self, *args) -> str:
        """计算 SHA1 签名"""
        raw = "".join(sorted(args))
        return hashlib.sha1(raw.encode()).hexdigest()

    def _pkcs7_pad(self, data: bytes, block_size: int = 32) -> bytes:
        pad = block_size - len(data) % block_size
        return data + bytes([pad] * pad)

    def _pkcs7_unpad(self, data: bytes) -> bytes:
        pad = data[-1]
        if pad < 1 or pad > 32:
            return data
        return data[:-pad]

    def _encrypt(self, text: str) -> bytes:
        """AES-256-CBC 加密"""
        # 16字节随机字符串
        random_str = "".join(random.choices(string.ascii_letters + string.digits, k=16))
        # 消息体：random(16) + msg_len(4) + msg + corp_id
        msg_bytes = text.encode("utf-8")
        msg_len = struct.pack("!I", len(msg_bytes))
        raw = random_str.encode() + msg_len + msg_bytes + self.corp_id.encode("utf-8")
        # PKCS7 填充
        raw = self._pkcs7_pad(raw)
        # AES-CBC 加密
        iv = self.aes_key[:16]
        cipher = AES.new(self.aes_key, AES.MODE_CBC, iv)
        return cipher.encrypt(raw)

    def _decrypt(self, encrypted: bytes) -> str:
        """AES-256-CBC 解密"""
        iv = self.aes_key[:16]
        cipher = AES.new(self.aes_key, AES.MODE_CBC, iv)
        raw = cipher.decrypt(encrypted)
        raw = self._pkcs7_unpad(raw)
        # 解析: random(16) + msg_len(4) + msg + corp_id
        msg_len = struct.unpack("!I", raw[16:20])[0]
        msg = raw[20:20 + msg_len].decode("utf-8")
        return msg

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> tuple[int, str]:
        """URL验证：验证回调URL的有效性"""
        # 计算签名
        signature = self._sha1(self.token, timestamp, nonce, echostr)
        if signature != msg_signature:
            return -1, "signature mismatch"
        # 解密 echostr
        try:
            decrypted = self._decrypt(base64.b64decode(echostr))
            return 0, decrypted
        except Exception as e:
            return -1, f"decrypt failed: {e}"

    def decrypt_msg(self, msg_signature: str, timestamp: str, nonce: str, encrypted_xml: str) -> tuple[int, str]:
        """解密企业微信推送的消息"""
        # 解析 XML 获取 Encrypt 字段
        root = ET.fromstring(encrypted_xml)
        encrypt_elem = root.find("Encrypt")
        if encrypt_elem is None:
            return -1, "no Encrypt element"
        encrypt = encrypt_elem.text

        # 验证签名
        signature = self._sha1(self.token, timestamp, nonce, encrypt)
        if signature != msg_signature:
            return -1, "signature mismatch"

        # 解密
        try:
            decrypted = self._decrypt(base64.b64decode(encrypt))
            return 0, decrypted
        except Exception as e:
            return -1, f"decrypt failed: {e}"

    def encrypt_msg(self, reply_text: str, nonce: str, timestamp: str = None) -> str:
        """加密回复消息，返回完整XML"""
        if timestamp is None:
            timestamp = str(int(time.time()))

        # 加密
        encrypted = self._encrypt(reply_text)
        encrypt_b64 = base64.b64encode(encrypted).decode()

        # 签名
        signature = self._sha1(self.token, timestamp, nonce, encrypt_b64)

        # 构建 XML
        xml = f"""<xml>
<Encrypt><![CDATA[{encrypt_b64}]]></Encrypt>
<MsgSignature><![CDATA[{signature}]]></MsgSignature>
<TimeStamp>{timestamp}</TimeStamp>
<Nonce><![CDATA[{nonce}]]></Nonce>
</xml>"""
        return xml


class WeComService:
    """企业微信服务层"""

    def __init__(self):
        self.corp_id = os.getenv("WECOM_CORP_ID", "")
        self.agent_id = os.getenv("WECOM_AGENT_ID", "")
        self.app_secret = os.getenv("WECOM_APP_SECRET", "")
        token = os.getenv("WECOM_TOKEN", "")
        encoding_aes_key = os.getenv("WECOM_ENCODING_AES_KEY", "")

        self.configured = bool(self.corp_id and token and encoding_aes_key)

        if self.configured:
            self.crypt = WXBizMsgCrypt(token, encoding_aes_key, self.corp_id)
            print(f"企微服务已配置: corp_id={self.corp_id[:8]}... agent_id={self.agent_id}")
        else:
            print("企微服务未配置（缺少 WECOM_CORP_ID / WECOM_TOKEN / WECOM_ENCODING_AES_KEY）")
            self.crypt = None

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> tuple[int, str]:
        """验证回调URL"""
        if not self.configured:
            return -1, "WeCom not configured"
        return self.crypt.verify_url(msg_signature, timestamp, nonce, echostr)

    def parse_message(self, msg_signature: str, timestamp: str, nonce: str, xml_body: str) -> dict | None:
        """解析企业微信推送的消息，返回标准化的消息字典"""
        if not self.configured:
            return None

        code, decrypted = self.crypt.decrypt_msg(msg_signature, timestamp, nonce, xml_body)
        if code != 0:
            print(f"消息解密失败: {decrypted}")
            return None

        # 解析解密后的 XML
        try:
            root = ET.fromstring(decrypted)
            msg = {
                "to_user": self._get_xml_text(root, "ToUserName"),
                "from_user": self._get_xml_text(root, "FromUserName"),
                "create_time": self._get_xml_text(root, "CreateTime"),
                "msg_type": self._get_xml_text(root, "MsgType"),
                "msg_id": self._get_xml_text(root, "MsgId"),
                "agent_id": self._get_xml_text(root, "AgentID"),
            }

            if msg["msg_type"] == "text":
                msg["content"] = self._get_xml_text(root, "Content")
            elif msg["msg_type"] == "image":
                msg["pic_url"] = self._get_xml_text(root, "PicUrl")
                msg["media_id"] = self._get_xml_text(root, "MediaId")
            elif msg["msg_type"] == "event":
                msg["event"] = self._get_xml_text(root, "Event")
                msg["event_key"] = self._get_xml_text(root, "EventKey")

            return msg
        except Exception as e:
            print(f"XML解析失败: {e}")
            return None

    def build_reply(self, to_user: str, from_user: str, content: str) -> str:
        """构建文本回复的 XML"""
        timestamp = str(int(time.time()))
        reply_xml = f"""<xml>
<ToUserName><![CDATA[{to_user}]]></ToUserName>
<FromUserName><![CDATA[{from_user}]]></FromUserName>
<CreateTime>{timestamp}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{content}]]></Content>
</xml>"""
        return reply_xml

    def encrypt_reply(self, reply_xml: str, nonce: str) -> str:
        """加密回复XML"""
        if not self.configured:
            return reply_xml
        return self.crypt.encrypt_msg(reply_xml, nonce)

    @staticmethod
    def _get_xml_text(element, tag: str) -> str:
        child = element.find(tag)
        return child.text if child is not None else ""


def get_host_ip() -> str:
    """获取本机内网 IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    svc = WeComService()
    if svc.configured:
        print("企微服务配置正常")
    else:
        print("企微服务未配置，请设置环境变量:")
        print("  WECOM_CORP_ID")
        print("  WECOM_AGENT_ID")
        print("  WECOM_APP_SECRET")
        print("  WECOM_TOKEN")
        print("  WECOM_ENCODING_AES_KEY")
    print(f"本机IP: {get_host_ip()}")
