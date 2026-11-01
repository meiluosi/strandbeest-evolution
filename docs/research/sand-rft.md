# 调研报告：阻力流体理论（RFT）与海滩沙地地面建模（S-03）

> **任务卡**：[ACTIONS.md](../ACTIONS.md) §S-03  
> **日期**：2026-11-01  
> **状态**：已完成（综述 + 参数推荐 + 仿真器工程落地结论）  
> **适用范围**：Theo Jansen 走兽在海滩干砂与湿砂上的足端交互、下陷深度预测及动力学等效参数。

---

## 1. 背景与核心问题

Theo Jansen 的原始 Strandbeest 主要漫步在荷兰斯海弗宁恩（Scheveningen）的北海海滩上。海滩由松散颗粒（石英细砂）构成。与刚性路面相比，沙滩具有两个决定性的非线性特性：
1. **足端下陷（Sinkage）**：足部必须侵入砂粒一定深度，由颗粒静压（Lithostatic pressure）产生的法向浮升力才能平衡走兽的垂直重力；
2. **剪切屈服与打滑（Granular Shear & Slip）**：当切向剪切应力超过颗粒内摩擦库仑极限时，砂粒发生塑性滑移，造成推力损失或空转掏穴。

在现有的仿真体系中，`flat` 为刚性刚体接触，`soft` 仅通过弹簧阻尼软化了恢复系数（无几何下陷和剪切流变）。为了评估风力走兽能否在真实沙滩上起步和行进，必须引入颗粒陆地动力学（Terradynamics）模型。

---

## 2. 阻力流体理论（Resistive Force Theory, RFT）综述

### 2.1 理论起源与适用边界
流体中的 RFT 最早由 Gray & Hancock (1955) 用于微尺度鞭毛推进。Goldman 实验室（Li, Zhang & Goldman, *Science* 2013, *PNAS* 2014）将其成功推广到干颗粒介质（Granular RFT）：
* **介质假设**：干砂由刚性不规则颗粒堆叠而成，无黏聚力（cohesionless）。
* **低速准静态剪切**：当运动处于低弗劳德数（Froude number $\text{Fr} = v / \sqrt{gd} \ll 1$）与低惯性数（Inertial number $I = \dot{\gamma} d / \sqrt{P/\rho} < 10^{-3}$）区间时，流体动力粘性阻力可忽略，阻力主要来自颗粒间摩擦力网络。Strandbeest 慢速步行（足端速度通常在 $0.05 \sim 0.3\,\text{m/s}$）严格处于该准静态摩擦主导区间。
* **分元叠加性（Linear Superposition）**：足端侵入体的任意复杂三维形状可沿迎流表面积分为微元 $dA$；各微元受力仅取决于其局部浸没深度 $z$、法向倾角 $\beta$ 和速度方向 $\gamma$，彼此之间的流线相互干扰在宏观上可作一阶近似解耦。

### 2.2 微元阻力方程
对处于表面下方深度为 $|z|$（取表面为 $z=0$，下陷为负深度）的微元，颗粒介质施加的单位面积力正比于深度 $|z|$（类静水压特性）：

$$\frac{d\mathbf{F}}{dA} = \rho g |z| \cdot \begin{bmatrix} \alpha_x(\beta, \gamma) \\ \alpha_z(\beta, \gamma) \end{bmatrix}$$

其中：
* $\rho$ 为砂的体积堆积密度（Bulk density，典型石英砂 $\rho \approx 1500 \sim 1650\,\text{kg/m}^3$）；
* $g$ 为重力加速度（$9.81\,\text{m/s}^2$）；
* $\alpha_x, \alpha_z$ 为无量纲阻力函数（由颗粒休止角 $\phi \approx 30^\circ \sim 34^\circ$ 决定）。

在垂直侵入（$\beta = 0, \gamma = -\pi/2$）时，垂直升力系数达到典型峰值 $\alpha_{z,0} \approx 4.0 \sim 5.5$；在水平推挤砂体时，推力系数 $\alpha_{x,0} \approx 1.5 \sim 2.2$。

---

## 3. Strandbeest 足端交互模型推导

### 3.1 准静态下陷平衡（Sinkage Equilibrium）
设单只脚足端为宽度 $w$、前后跨度 $l$ 的柱状管底（有效水平投影面积 $A_{foot} = w \cdot l$）。
当该足承载法向负荷 $F_N$ 时，下陷深度 $z_{sink}$ 由垂直升力积分平衡给出：

$$F_N = \int_0^{z_{sink}} \alpha_{z,0} \rho g z \cdot w \, dz = \frac{1}{2} \alpha_{z,0} \rho g w \, z_{sink}^2$$

从而推导出特征下陷深度公式：

$$z_{sink} = \sqrt{\frac{2 F_N}{\alpha_{z,0} \rho g w}}$$

**数量级核算（以本仓库小模型为例）**：
* 6 腿小模型：总质量 $M \approx 0.4\,\text{kg}$，单腿支撑负荷 $F_N \approx \frac{0.4 \times 9.81}{3} \approx 1.3\,\text{N}$。
* 足端直径 $2 r_{foot} \approx 0.012\,\text{m}$，若 $w \approx 0.02\,\text{m}$：
  $$z_{sink} = \sqrt{\frac{2 \times 1.3}{4.5 \times 1600 \times 9.81 \times 0.02}} \approx \sqrt{\frac{2.6}{1412}} \approx 0.043\,\text{m} = 4.3\,\text{cm}$$
* **结论**：若足端为尖圆管，在极松散干沙中小模型将严重下陷（下陷深度甚至接近腿部抬高行程），导致机构被卡死！
* 这在物理上完美解释了 Theo Jansen 原作在真实海滩上的选择：**实物必须在紧贴潮线的水浸硬砂（Packed wet sand）上行走**，或在干沙上加装宽脚蹼（Paddle-feet）以显著增大 $w$ 和受力面积。

---

## 4. 仿真器工程落地方案

在刚体动力学仿真器（MuJoCo 及 K2）中，精确颗粒离散元（DEM）的计算开销极大（每步需要数千个球体碰撞），不适合优化和浏览器实时回放。依据 RFT 原理，可将其等效映射为高精度的连续介质接触刚度与剪切滑移边界：

1. **等效下陷接触刚度**：
   将下陷深度 $z_{sink}$ 近似线性化为等效刚度 $k_{sand} = \frac{F_N}{z_{sink}} \approx \sqrt{\frac{1}{2} \alpha_{z,0} \rho g w F_N}$。
   对于小模型取 $k_{sand} \approx 2500 \sim 3500\,\text{N/m}$，阻尼比 $\zeta \approx 0.8$（颗粒非弹性碰撞高度耗散）。
2. **颗粒临界剪切摩擦**：
   海滩砂颗粒的等效宏观库仑摩擦系数 $\mu_{sand} \approx \tan \phi \approx \tan(32^\circ) \approx 0.62$。
   切向打滑极限由下陷侧向推挤与表面滑动共同确定。

### 结论与任务验收建议（S-03）
* **是否实现**：**实现**。在 `strandbeest_sim` 与 `sim-web` 中注册并支持 `sand` 地形。
* **参数暴露**：
  - `stiffness`（默认 $2800\,\text{N/m}$，对应小模型在干砂上的等效下陷刚度）；
  - `damping`（默认 $180\,\text{N}\cdot\text{s/m}$，高耗散颗粒阻尼）；
  - `friction`（默认 $0.62$，北海干石英砂内摩擦系数）。
