# Evidence Graph: 双重暗影

## Conclusion 1: 真凶身份 — 幸存者是周正 (weight 0.40)
**Answer**: npc_survivor_lu 实际上是周正。

**Supporting evidence**:
1. `ev_medical_allergy_record` — 真正的陆远山对海鲜严重过敏，而幸存者却吃了海鲜餐。 -> strong
2. `ev_dental_record_discrepancy` — 牙医档案与幸存者身体特征不符。 -> strong
3. `npc_wife_shen_tier_3` — 妻子的直觉供述，指出丈夫行为模式的彻底改变。 -> medium

**Discovery path**:
```
[陆家] → 发现过敏病历 (ev_medical_allergy_record) → 对照沈嘉宁供述 (晚餐内容) 
        → 产生怀疑 → 询问老K (ev_dental_record_discrepancy) → [确认结论]
```

## Conclusion 2: 作案动机 — 复仇与身份窃取 (weight 0.20)
**Answer**: 周正要夺回被陆远山窃取的人生。

**Supporting evidence**:
1. `ev_old_manuscript_scrap` — 烂尾楼的手稿显示算法归属于周正。 -> strong
2. `npc_old_k_tier_4` — 证人之父揭露当年的非法交易。 -> medium

## Conclusion 3: 作案手法 — 仪式性替换 (weight 0.20)
**Answer**: 利用绑架作为掩护杀人，并现场替换身份。

**Supporting evidence**:
1. `ev_old_k_hidden_phone` — 杀人后练习笑容的视频。 -> strong
2. `ev_fake_hair_and_voice_changer` — 现场遗留的变声设备。 -> medium

## Red Herrings
### rh_wife_motive: 沈嘉宁毒害亲夫案
**Theory**: 妻子为财杀人。
**Resolution**: `ev_wife_diary` 显示沈嘉宁是因为害怕眼前的冒牌货才准备药物并咨询离婚。

## Timeline
- T-10y: 剽窃案背景。
- T-48h: 陆远山失踪。
- T-2h: 致命杀戮，周正对着镜子练习。
- T-0: 警方突袭，周正以陆远山身份获救。
