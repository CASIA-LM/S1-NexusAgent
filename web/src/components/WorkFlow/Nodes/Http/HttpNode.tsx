import { Box, HStack, IconButton, Text, VStack } from "@chakra-ui/react";
import React from "react";
import { FiServer, FiGlobe } from "react-icons/fi";
import { Handle, type NodeProps, Position } from "reactflow";

import { BaseNode } from "../Base/BaseNode";
import { nodeConfig } from "../nodeConfig";

interface HttpEndpoint {
  url: string;
  method: string;
  timeout: number;
}

const HttpNode: React.FC<NodeProps> = (props) => {
  // 获取节点配置
  const { icon: Icon, colorScheme } = nodeConfig.http;
  
  // 处理HTTP端点数据
  const httpEndpoints = Array.isArray(props.data.endpoints)
    ? props.data.endpoints
    : [props.data]; // 默认为当前节点数据

  // 统一的连接点样式
  const handleStyle = {
    background: "var(--chakra-colors-ui-wfhandlecolor)",
    width: 8,
    height: 8,
    border: "2px solid white",
    transition: "all 0.2s",
  };

  return (
    <BaseNode {...props} icon={<Icon />} colorScheme={colorScheme}>
      {/* 输入连接点 - 匹配边数据中的targetHandle */}
      <Handle
        type="target"
        position={Position.Left}
        id="left"  // 与边数据中的targetHandle: "left"匹配
        style={handleStyle}
      />
      <Handle
        type="target"
        position={Position.Top}
        id="top"   // 标准命名便于识别
        style={handleStyle}
      />
      
      {/* 输出连接点 - 匹配边数据中的sourceHandle */}
      <Handle
        type="source"
        position={Position.Right}
        id="right"  // 标准命名便于识别
        style={handleStyle}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        id="bottom" // 与边数据中的sourceHandle: "bottom"匹配
        style={handleStyle}
      />

      {/* 节点内容区域 */}
      <VStack align="stretch" spacing={1} p={1}>
        {httpEndpoints.length > 0 ? (
          httpEndpoints.map((endpoint: string | HttpEndpoint, index: number) => {
            // 处理不同格式的端点数据
            let displayUrl, method;
            if (typeof endpoint === "string") {
              displayUrl = endpoint;
              method = "GET"; // 默认方法
            } else {
              displayUrl = endpoint.url || "undefined";
              method = endpoint.method || "GET";
            }

            // 简化显示的URL
            const shortUrl = displayUrl.length > 30 
              ? `${displayUrl.slice(0, 27)}...` 
              : displayUrl;

            return (
              <Box
                key={index}
                bg="ui.inputbgcolor"
                borderRadius="md"
                p={2}
                transition="all 0.2s"
                _hover={{
                  bg: "gray.100",
                  transform: "translateY(-1px)",
                  boxShadow: "sm",
                }}
              >
                <HStack spacing={2} px={1} align="center">
                  {/* 方法标签 */}
                  <Box
                    fontSize="xx-small"
                    fontWeight="bold"
                    px={1.5}
                    py={0.5}
                    borderRadius="full"
                    bg={method === "POST" ? "green.100" : "blue.100"}
                    color={method === "POST" ? "green.800" : "blue.800"}
                  >
                    {method}
                  </Box>
                  
                  {/* URL显示 */}
                  <HStack align="center" flex={1} overflow="hidden">
                    <FiGlobe size="12px" color="gray.500" />
                    <Text
                      fontSize="xs"
                      color="gray.700"
                      noOfLines={1}
                      whiteSpace="nowrap"
                      overflow="hidden"
                      textOverflow="ellipsis"
                    >
                      {shortUrl}
                    </Text>
                  </HStack>
                  
                  {/* 服务器图标 */}
                  <IconButton
                    aria-label="HTTP endpoint"
                    icon={<FiServer size="14px" />}
                    colorScheme={colorScheme}
                    size="xs"
                    variant="ghost"
                    transition="all 0.2s"
                    _hover={{
                      transform: "scale(1.1)",
                    }}
                  />
                </HStack>
              </Box>
            );
          })
        ) : (
          <Text
            fontSize="xs"
            color="gray.500"
            textAlign="center"
            fontWeight="500"
            p={2}
          >
            No HTTP endpoint configured
          </Text>
        )}
      </VStack>
    </BaseNode>
  );
};

export default React.memo(HttpNode);