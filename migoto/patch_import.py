import bpy
import os
import functools
import sys

# =============================================================================
# 1. 核心逻辑：路径强制清洗与更新
# =============================================================================
def force_update_dump_path(scene_name, new_path):
    """
    延迟执行的核弹级更新函数：
    1. 找到场景
    2. 暴力清空路径 -> 强制刷新
    3. 填入新路径 -> 强制刷新
    """
    try:
        scene = bpy.data.scenes.get(scene_name)
        if not scene or not hasattr(scene, "xxmi"): 
            return

        # --- 步骤 A: 暴力清空 ---
        # 这一步至关重要，它强制触发属性的 update 回调
        scene.xxmi.dump_path = ""
        
        # 强制通知 Blender 界面数据变了
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
        
        # --- 步骤 B: 写入新值 ---
        # 使用 os.path.normpath 确保路径格式标准
        final_path = os.path.normpath(new_path)
        scene.xxmi.dump_path = final_path
        
        print(f"[XXMI] Dump Folder 已自动更新为: {final_path}")
        
        # 再次刷新
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
                
    except Exception as e:
        print(f"[XXMI Error] 路径更新过程崩溃: {e}")

# =============================================================================
# 2. Hook (钩子) 逻辑
# =============================================================================
OriginalExecute = None

def execute_hook(self, context):
    """
    植入到原版插件的逻辑
    """
    # 1. 先执行原版导入
    if OriginalExecute:
        try:
            result = OriginalExecute(self, context)
        except Exception as e:
            print(f"[XXMI Error] 原版导入器报错: {e}")
            return {'CANCELLED'}
    else:
        return {'CANCELLED'}

    # 2. 如果导入成功，且开关是开启的，启动自动填充
    # 检查开关状态
    is_enabled = getattr(context.scene, "xxmi_auto_fill_enabled", True)
    
    if 'FINISHED' in result and is_enabled:
        try:
            filepath = getattr(self, "filepath", "")
            if filepath:
                dump_dir = os.path.dirname(filepath)
                # 注册延迟任务 (延迟 0.1 秒)
                bpy.app.timers.register(
                    functools.partial(force_update_dump_path, context.scene.name, dump_dir),
                    first_interval=0.1
                )
        except Exception as e:
            print(f"[XXMI Warning] 路径钩子注册失败: {e}")

    return result

# =============================================================================
# 3. UI 面板
# =============================================================================
class XXMI_PT_ImportPanel(bpy.types.Panel):
    bl_label = "自动补充顶点组导出"
    bl_idname = "XXMI_PT_ImportPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_parent_id = "XXMI_PT_Sidebar"
    bl_order = 0 

    def draw(self, context):
        layout = self.layout
        
        op_id = "import_mesh.migoto_frame_analysis"
        
        if hasattr(bpy.ops.import_mesh, "migoto_frame_analysis"):
            # 开关
            row = layout.row()
            row.prop(context.scene, "xxmi_auto_fill_enabled", text="启用路径自动填充")
            
            # 按钮
            row = layout.row()
            row.scale_y = 1.5
            row.operator(op_id, text="导入模型 (ib.txt+vb.txt)", icon='IMPORT')
            
            # 状态提示
            if not OriginalExecute:
                 pass 
            else:
                 # 如果成功hook，这里可以什么都不显示，或者显示一个小图标
                 pass
        else:
            box = layout.box()
            box.label(text="未检测到 3DMigoto 插件", icon="ERROR")

# =============================================================================
# 4. 注册与注入 (修正版)
# =============================================================================
def register():
    global OriginalExecute
    
    # 1. 注册属性 (开关)
    # 属性必须手动注册，auto_load 不管这个
    bpy.types.Scene.xxmi_auto_fill_enabled = bpy.props.BoolProperty(
        name="Auto-Fill Dump Path",
        description="导入完成后自动将 Dump Folder 设置为文件所在目录",
        default=True
    )
    
    # 【核心修复】删除了 bpy.utils.register_class(XXMI_PT_ImportPanel)
    # 因为 auto_load.py 已经帮我们注册了这个类
    
    # 2. 寻找目标类 (全域搜索模式)
    TargetClass = None
    
    # 策略 A: 尝试相对导入
    try:
        from . import import_ops
        if hasattr(import_ops, "Import3DMigotoFrameAnalysis"):
            TargetClass = import_ops.Import3DMigotoFrameAnalysis
    except ImportError:
        pass

    # 策略 B: 全局搜索
    if TargetClass is None:
        # print("[XXMI] 正在全局搜索 Import3DMigotoFrameAnalysis 类...")
        for name, module in sys.modules.items():
            if 'migoto' in name and 'import_ops' in name:
                if hasattr(module, "Import3DMigotoFrameAnalysis"):
                    TargetClass = getattr(module, "Import3DMigotoFrameAnalysis")
                    # print(f"[XXMI] 在模块 '{name}' 中找到了目标类")
                    break
    
    # 3. 执行注入
    if TargetClass:
        if not hasattr(TargetClass, "xxmi_hooked"):
            OriginalExecute = TargetClass.execute
            TargetClass.execute = execute_hook
            TargetClass.xxmi_hooked = True
            print("[XXMI] 3DMigoto 导入钩子挂载成功")
        else:
            # 已经挂载过，更新引用
            OriginalExecute = TargetClass.execute
            if OriginalExecute != execute_hook:
                 TargetClass.execute = execute_hook
    else:
        print("[XXMI Error] 严重错误：未找到导入类，自动填充不可用")

def unregister():
    # 1. 注销属性
    del bpy.types.Scene.xxmi_auto_fill_enabled
    
    # 【核心修复】删除了 bpy.utils.unregister_class
    
    # 2. 尝试还原 Hook
    pass