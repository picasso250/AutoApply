import json # 导入 json 模块
import os # 导入 os 模块，因为ConfigManager可能需要创建目录

class ConfigManager:
    """
    管理配置文件 (config.json) 的读取和写入。
    用于存储根目录等配置信息。
    """
    def __init__(self, config_file='config.json'): # 更改为 config.json
        self.config_file = config_file
        self.config_data = {} # 存储 JSON 数据字典
        self._load_config() 

    def _load_config(self):
        """加载配置文件，如果不存在则 config_data 将为空字典。"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config_data = json.load(f)
        except FileNotFoundError:
            self.config_data = {} # 文件不存在，初始化为空字典
        except json.JSONDecodeError as e:
            print(f"[WARNING] 配置文件 '{self.config_file}' 格式错误: {e}. 将使用空配置。", file=sys.stderr)
            self.config_data = {} # JSON 格式错误，初始化为空字典
        except Exception as e:
            print(f"[WARNING] 无法加载配置文件 '{self.config_file}': {e}", file=sys.stderr)
            self.config_data = {}

    def get_root_folder(self):
        """获取配置的根目录。如果不存在，则返回空字符串。"""
        # 根据约定好的 JSON 结构 {"root_folder": "..."}
        return self.config_data.get('root_folder', '').strip()

    def set_root_folder(self, path):
        """设置根目录并保存。"""
        self.config_data['root_folder'] = path
        self._save_config()

    def _save_config(self):
        """保存配置文件。"""
        # 确保配置文件目录存在
        config_dir = os.path.dirname(self.config_file)
        if config_dir and not os.path.exists(config_dir):
            try:
                os.makedirs(config_dir, exist_ok=True)
            except OSError as e:
                # 注意：这里我们不能直接使用 Tkinter 的 messagebox，
                # 因为 config_manager 应该是一个独立的、不依赖 GUI 的模块。
                # 暂时使用 print，将来可以在 AutoCodeApplier 中捕获并处理。
                print(f"[ERROR] 无法创建配置目录 '{config_dir}': {e}", file=sys.stderr)
                return

        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config_data, f, indent=2, ensure_ascii=False) # 写入 JSON，并进行2空格缩进
        except IOError as e:
            print(f"[ERROR] 无法保存配置文件 '{self.config_file}': {e}", file=sys.stderr)
